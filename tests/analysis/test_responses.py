import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.analysis.check_responses import validate_analysis_responses


def sample():
    generation='a'*20
    catalog=dict(dataset_id='teaching-v1',generation_id=generation,model_type='synthetic_demo',analysis_srid=32650,depth_unit='m',threshold_m=.1,
                 scenarios=[dict(scenario_id=s,name=s,steps=[dict(step_id=f'{s}_T{t:02}',step_code=f'T{t:02}',time_min=t,layer_id=f'flood:depth_{s}_T{t:02}') for t in (0,30,60)]) for s in ('S01','S02')])
    reference=dict(status='ok',analysis_srid=32650,steps=[]);summaries={};collections={}
    geometry=dict(type='Polygon',coordinates=[[[117.,30.],[117.001,30.],[117.001,30.001],[117.,30.]]])
    for scenario in catalog['scenarios']:
        for step in scenario['steps']:
            step_id=step['step_id'];wet=step['time_min']!=0
            buildings=[dict(building_id=f'B{i:03}',name=f'教学{i}',usage='demo',affected=wet and i<4,geometry=copy.deepcopy(geometry)) for i in range(1,5)]
            reference['steps'].append(dict(step_id=step_id,flooded_area_m2=150. if wet else 0.,affected_building_ids=[b['building_id'] for b in buildings if b['affected']],flooded_road_length_m=30. if wet else 0.,buildings=buildings))
            identity=dict(step_id=step_id,dataset_id='teaching-v1',generation_id=generation,model_type='synthetic_demo',analysis_srid=32650,threshold_m=.1)
            summaries[step_id]=dict(**identity,flooded_area_m2=150. if wet else 0.,affected_buildings=3 if wet else 0,flooded_road_length_m=30. if wet else 0.)
            collections[step_id]=dict(type='FeatureCollection',features=[dict(type='Feature',id=b['building_id'],properties={k:b[k] for k in ('building_id','name','usage','affected')},geometry=copy.deepcopy(b['geometry'])) for b in buildings],metadata=dict(**identity,geometry_srid=4326,limit=200,returned_count=4,total_buildings=4,truncated=False))
    return catalog,reference,summaries,collections


class ResponseTests(unittest.TestCase):
    def test_ring_direction_and_start_vertex_do_not_change_geometry(self):
        for kind in ('reverse','rotate'):
            values=sample()
            ring=values[3]['S01_T30']['features'][0]['geometry']['coordinates'][0]
            points=ring[:-1]
            points=list(reversed(points)) if kind=='reverse' else points[1:]+points[:1]
            values[3]['S01_T30']['features'][0]['geometry']['coordinates'][0]=points+[points[0]]
            self.assertEqual(validate_analysis_responses(*values)['status'],'ok')

    def test_valid_full_and_truncated(self):
        values=sample();report=validate_analysis_responses(*values)
        self.assertEqual(report['status'],'ok');self.assertEqual(len(report['steps']),6)
        for collection in values[3].values():
            collection['features']=collection['features'][:1]
            collection['metadata'].update(limit=1,returned_count=1,truncated=True)
        self.assertEqual(validate_analysis_responses(*values)['status'],'ok')

    def test_exact_fields_sets_geometry_flags_and_version(self):
        for change in ('html','extra','wrong_ids','affected','axis','clipped','generation','wrong_step','truncated','missing','negative','nan','bool_count'):
            with self.subTest(change=change):
                values=sample();summary=values[2]['S01_T30'];collection=values[3]['S01_T30']
                if change=='html':values[2]['S01_T30']='<html>Error</html>'
                elif change=='extra':summary['password']='not allowed'
                elif change=='wrong_ids':collection['features'][0]['id']='B999'
                elif change=='affected':collection['features'][0]['properties']['affected']=False
                elif change=='axis':collection['features'][0]['geometry']['coordinates'][0][0]=[30.,117.]
                elif change=='clipped':collection['features'][0]['geometry']['coordinates'][0][1][0]=117.0005
                elif change=='generation':summary['generation_id']='b'*20
                elif change=='wrong_step':summary['step_id']='S02_T30'
                elif change=='truncated':collection['metadata']['truncated']=True
                elif change=='missing':del values[3]['S02_T60']
                elif change=='negative':summary['flooded_area_m2']=-1
                elif change=='nan':summary['flooded_area_m2']=float('nan')
                else:summary['affected_buildings']=True
                with self.assertRaises(ValueError):validate_analysis_responses(*values)

    def test_numerical_tolerances(self):
        for field in ('flooded_area_m2','flooded_road_length_m'):
            for difference,allowed in ((.009,True),(.011,False)):
                values=sample();values[2]['S01_T30'][field]+=difference
                if allowed:self.assertEqual(validate_analysis_responses(*values)['status'],'ok')
                else:
                    with self.assertRaises(ValueError):validate_analysis_responses(*values)


if __name__=='__main__':unittest.main()
