from contextlib import nullcontext
from urllib.parse import urlencode

import psycopg
import pytest

from app import analysis_routes
from app.analysis_store import AnalysisDataUnavailable
from test_health import get


def summary(step_id):
    return dict(step_id=step_id, dataset_id='teaching-v1', generation_id='a'*20, model_type='synthetic_demo',
                analysis_srid=32650, threshold_m=.1, flooded_area_m2=150., affected_buildings=3, flooded_road_length_m=30.)


def collection(step_id, limit):
    identity = {k:v for k,v in summary(step_id).items() if k not in ('flooded_area_m2','affected_buildings','flooded_road_length_m')}
    features = [dict(type='Feature', id=f'B{i:03}', properties=dict(building_id=f'B{i:03}', name='教学建筑', usage='demo', affected=i<=3),
                    geometry=dict(type='Polygon', coordinates=[[[117.,30.],[117.001,30.],[117.001,30.001],[117.,30.]]])) for i in range(1,min(limit,200)+1)]
    return dict(type='FeatureCollection', features=features, metadata=dict(**identity,geometry_srid=4326,limit=limit,returned_count=len(features),total_buildings=200,truncated=len(features)<200))


@pytest.fixture
def store(monkeypatch):
    calls=[]
    monkeypatch.setattr(analysis_routes,'open_database',lambda: nullcontext(object()))
    monkeypatch.setattr(analysis_routes,'read_summary',lambda c,s: calls.append(('summary',s)) or summary(s))
    monkeypatch.setattr(analysis_routes,'read_buildings',lambda c,s,l: calls.append(('buildings',s,l)) or collection(s,l))
    return calls


@pytest.mark.parametrize('step_id',[f'{s}_T{t:02}' for s in ('S01','S02') for t in (0,30,60)])
def test_success_contracts(store,step_id):
    response=get('/api/v1/analysis/summary?'+urlencode({'step_id':step_id}))
    assert response.status_code==200 and response.json()==summary(step_id)
    response=get('/api/v1/analysis/buildings?'+urlencode({'step_id':step_id}))
    assert response.status_code==200 and response.json()==collection(step_id,200)


@pytest.mark.parametrize('query',['','step_id=','step_id=s01_T30','step_id=S01_T30%20','step_id=%20S01_T30',
 'step_id=S01_T30%0A','step_id=4','step_id=S01_T30%27%3BDROP+TABLE+x','step_id=S03_T30',
 'step_id=S01_T30&step_id=S02_T60','step_id=S01_T30&CQL_FILTER=1%3D1'])
@pytest.mark.parametrize('endpoint',['summary','buildings'])
def test_invalid_or_unknown_never_opens_database(monkeypatch,query,endpoint):
    def forbidden(): pytest.fail('Invalid input must not connect')
    monkeypatch.setattr(analysis_routes,'open_database',forbidden)
    response=get(f'/api/v1/analysis/{endpoint}?{query}')
    assert response.status_code==(404 if query=='step_id=S03_T30' else 422)
    if response.status_code==404: assert response.json()=={'detail':'step not found'}


@pytest.mark.parametrize('limit',['0','501','-1','1.5','1.0','%2B1','1e2','%20','', '1&limit=2'])
def test_invalid_limit_never_opens_database(monkeypatch,limit):
    monkeypatch.setattr(analysis_routes,'open_database',lambda: pytest.fail('Invalid limit must not connect'))
    assert get(f'/api/v1/analysis/buildings?step_id=S01_T30&limit={limit}').status_code==422


def test_valid_limits_and_summary_rejects_limit(store):
    for limit in (1,500):
        response=get(f'/api/v1/analysis/buildings?step_id=S01_T30&limit={limit}')
        assert response.status_code==200 and response.json()['metadata']['limit']==limit
    assert get('/api/v1/analysis/summary?step_id=S01_T30&limit=1').status_code==422
    assert store==[('buildings','S01_T30',1),('buildings','S01_T30',500)]


@pytest.mark.parametrize('error,detail',[(psycopg.OperationalError,'database unavailable'),(psycopg.errors.QueryCanceled,'database unavailable'),(AnalysisDataUnavailable,'analysis data unavailable')])
@pytest.mark.parametrize('endpoint',['summary','buildings'])
def test_failures_are_sanitized_and_recover(monkeypatch,caplog,store,error,detail,endpoint):
    def unavailable(*args): raise error('password=private-test-secret SELECT * FROM hidden')
    name='read_summary' if endpoint=='summary' else 'read_buildings'
    monkeypatch.setattr(analysis_routes,name,unavailable)
    response=get(f'/api/v1/analysis/{endpoint}?step_id=S01_T30')
    assert response.status_code==503 and response.json()=={'detail':detail}
    assert 'private-test-secret' not in response.text+caplog.text
    assert 'SELECT *' not in response.text+caplog.text
    monkeypatch.setattr(analysis_routes,name,(lambda c,s: summary(s)) if endpoint=='summary' else (lambda c,s,l: collection(s,l)))
    assert get(f'/api/v1/analysis/{endpoint}?step_id=S01_T30').status_code==200


def test_connection_failure_is_sanitized(monkeypatch,caplog):
    def fail(): raise psycopg.OperationalError('private-test-secret')
    monkeypatch.setattr(analysis_routes,'open_database',fail)
    assert get('/api/v1/analysis/summary?step_id=S01_T30').json()=={'detail':'database unavailable'}
    assert 'private-test-secret' not in caplog.text


def test_openapi_documents_both_endpoints():
    schema=get('/openapi.json').json()
    for endpoint in ('summary','buildings'):
        parameters=schema['paths'][f'/api/v1/analysis/{endpoint}']['get']['parameters']
        assert next(p for p in parameters if p['name']=='step_id')['required'] is True
    params=schema['paths']['/api/v1/analysis/buildings']['get']['parameters']
    assert '500' in next(p for p in params if p['name']=='limit')['description']
