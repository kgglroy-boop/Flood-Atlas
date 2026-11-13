import copy
import io
import json

import psycopg
import pytest

from teaching_fixtures import valid_payload
from app.teaching_payload import validate_payload
from app import import_teaching_data as cli


def test_accepts_unicode_and_apostrophe_as_values():
    p = valid_payload()
    p['buildings'][0]['name'] = "教学建筑 O'Brien"
    assert validate_payload(p)['buildings'][0]['name'] == "教学建筑 O'Brien"


@pytest.mark.parametrize('kind', ['crs', 'missing', 'duplicate', 'time', 'path', 'area', 'wkb', 'foreign', 'empty'])
def test_rejects_invalid_payload_before_writes(kind):
    p = valid_payload()
    if kind == 'crs':
        p['analysis_srid'] = 4326
    elif kind == 'missing':
        del p['roads']
    elif kind == 'duplicate':
        p['buildings'][1]['building_id'] = 'B001'
    elif kind == 'time':
        p['steps'][1]['time_min'] = 15
    elif kind == 'path':
        p['steps'][0]['raster_relative_path'] = '../elsewhere.tif'
    elif kind == 'area':
        p['flood_extents'][1]['area_m2'] = float('nan')
    elif kind == 'wkb':
        p['buildings'][0]['geom_wkb_hex'] = '010300'
    elif kind == 'foreign':
        p['buildings'][0]['dataset_id'] = 'user-data'
    else:
        p['buildings'][0]['geom_wkb_hex'] = '010300000000000000'
    with pytest.raises(ValueError):
        validate_payload(p)


def test_cli_sanitizes_connection_failure(monkeypatch, capsys):
    secret = 'test-password-not-for-output'
    def fail():
        raise psycopg.OperationalError(f'password={secret} host=db')
    monkeypatch.setattr(cli, '_connect', fail)
    assert cli.main([], stdin=io.StringIO(json.dumps(valid_payload()))) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert 'host=db' not in output.out + output.err
    assert json.loads(output.out)['status'] == 'error'


def test_cli_rejects_duplicate_json_keys_without_connecting(monkeypatch, capsys):
    monkeypatch.setattr(cli, '_connect', lambda: pytest.fail('Must validate JSON before connecting'))
    assert cli.main([], stdin=io.StringIO('{"dataset_id":"a","dataset_id":"b"}')) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'error'
