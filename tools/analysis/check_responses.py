"""Independently verify six HTTP analysis results against QGIS reference values."""
import argparse
import json
import math
import re
from pathlib import Path

IDENTITY={'step_id','dataset_id','generation_id','model_type','analysis_srid','threshold_m'}
METRICS={'flooded_area_m2','affected_buildings','flooded_road_length_m'}
META=IDENTITY|{'geometry_srid','limit','returned_count','total_buildings','truncated'}
STEPS={f'{s}_T{t:02}' for s in ('S01','S02') for t in (0,30,60)}


def _require(condition,message='Analysis response contract mismatch'):
    if not condition:raise ValueError(message)


def _keys(value,expected):
    _require(isinstance(value,dict) and set(value)==expected)


def _number(value):
    _require(type(value) in (int,float) and math.isfinite(value) and value>=0)
    return value


def _same_coordinates(actual,expected):
    if isinstance(expected,list):
        _require(isinstance(actual,list) and len(actual)==len(expected))
        for a,e in zip(actual,expected):_same_coordinates(a,e)
    else:
        _require(type(actual) in (int,float) and type(expected) in (int,float) and
                 math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected)<=1e-8,'Building coordinates mismatch')


def _same_polygon(actual,expected):
    _require(isinstance(actual,list) and len(actual)==len(expected) and len(actual)>0)
    for ring,reference_ring in zip(actual,expected):
        _require(isinstance(ring,list) and len(ring)==len(reference_ring) and len(ring)>=4)
        for point in ring:
            _require(isinstance(point,list) and len(point)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in point))
            _require(-180<=point[0]<=180 and -90<=point[1]<=90)
        _same_coordinates(ring[0],ring[-1])
        # Polygon ring direction and starting vertex are serialization choices.
        # Preserve adjacency: sorting a vertex set would also accept crossed rings.
        points=ring[:-1];reference_points=reference_ring[:-1]
        match=False
        for ordered in (points,list(reversed(points))):
            for start in range(len(ordered)):
                rotated=ordered[start:]+ordered[:start]
                if all(all(abs(a-e)<=1e-8 for a,e in zip(p,q)) for p,q in zip(rotated,reference_points)):
                    match=True;break
            if match:break
        _require(match,'Building coordinates mismatch')


def validate_analysis_responses(catalog:dict,reference:dict,summaries:dict,collections:dict)->dict:
    _require(isinstance(catalog,dict) and catalog.get('dataset_id')=='teaching-v1' and catalog.get('model_type')=='synthetic_demo' and
             catalog.get('analysis_srid')==32650 and catalog.get('threshold_m')==.1 and catalog.get('depth_unit')=='m')
    generation=catalog.get('generation_id')
    _require(isinstance(generation,str) and re.fullmatch('[0-9a-f]{20}',generation) is not None)
    scenarios=catalog.get('scenarios')
    _require(isinstance(scenarios,list) and len(scenarios)==2 and {s.get('scenario_id') for s in scenarios}=={'S01','S02'})
    steps=[]
    for scenario in scenarios:
        _require(isinstance(scenario.get('steps'),list) and len(scenario['steps'])==3)
        for step in scenario['steps']:
            _require(isinstance(step,dict) and type(step.get('time_min')) is int and step['time_min'] in (0,30,60))
            step_id=f"{scenario['scenario_id']}_T{step['time_min']:02}"
            _require(step.get('step_id')==step_id and step.get('step_code')==f"T{step['time_min']:02}" and step.get('layer_id')=='flood:depth_'+step_id)
            steps.append(step_id)
    _require(len(steps)==6 and set(steps)==STEPS)
    _require(isinstance(reference,dict) and reference.get('status')=='ok' and reference.get('analysis_srid')==32650 and isinstance(reference.get('steps'),list))
    _require(len(reference['steps'])==6 and {s.get('step_id') for s in reference['steps']}==STEPS)
    refs={s['step_id']:s for s in reference['steps']}
    _keys(summaries,STEPS);_keys(collections,STEPS)
    results=[]
    for step_id in sorted(STEPS):
        ref=refs[step_id];summary=summaries[step_id];collection=collections[step_id]
        identity=dict(step_id=step_id,dataset_id='teaching-v1',generation_id=generation,model_type='synthetic_demo',analysis_srid=32650,threshold_m=.1)
        _keys(summary,IDENTITY|METRICS)
        _require(all(summary[k]==v for k,v in identity.items()))
        area=_number(summary['flooded_area_m2']);length=_number(summary['flooded_road_length_m'])
        count=summary['affected_buildings'];_require(type(count) is int and count>=0)
        ids=ref['affected_building_ids']
        buildings=ref['buildings']
        _require(isinstance(ids,list) and ids==sorted(set(ids)) and isinstance(buildings,list))
        _require([b['building_id'] for b in buildings]==sorted({b['building_id'] for b in buildings}))
        _require(ids==[b['building_id'] for b in buildings if b['affected']] and count==len(ids))
        area_difference=abs(area-_number(ref['flooded_area_m2']))
        length_difference=abs(length-_number(ref['flooded_road_length_m']))
        _require(area_difference<=.01 and length_difference<=.01,'Analysis measurements differ from QGIS')
        _keys(collection,{'type','features','metadata'})
        _require(collection['type']=='FeatureCollection' and isinstance(collection['features'],list))
        metadata=collection['metadata'];_keys(metadata,META)
        _require(all(metadata[k]==v for k,v in identity.items()) and metadata['geometry_srid']==4326)
        for key in ('limit','returned_count','total_buildings'):_require(type(metadata[key]) is int)
        total=len(buildings);limit=metadata['limit'];features=collection['features']
        _require(1<=limit<=500 and metadata['total_buildings']==total and len(features)==min(limit,total) and metadata['returned_count']==len(features))
        _require(type(metadata['truncated']) is bool and metadata['truncated']==(len(features)<total))
        for feature,expected in zip(features,buildings[:limit]):
            _keys(feature,{'type','id','properties','geometry'})
            _require(feature['type']=='Feature' and feature['id']==expected['building_id'])
            properties=feature['properties'];_keys(properties,{'building_id','name','usage','affected'})
            _require(type(properties['affected']) is bool and all(properties[k]==expected[k] for k in properties))
            geometry=feature['geometry'];_keys(geometry,{'type','coordinates'})
            _require(geometry['type']=='Polygon' and expected['geometry']['type']=='Polygon')
            _same_polygon(geometry['coordinates'],expected['geometry']['coordinates'])
        results.append(dict(step_id=step_id,flooded_area_m2=area,affected_buildings=count,affected_building_ids=ids,
                            flooded_road_length_m=length,area_difference_m2=area_difference,length_difference_m=length_difference,
                            returned_count=len(features),truncated=metadata['truncated']))
    return dict(status='ok',generation_id=generation,steps=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    try:
        payload=json.loads(args.input.read_text(encoding='utf-8-sig'))
        _keys(payload,{'catalog','reference','summaries','collections'})
        print(json.dumps(validate_analysis_responses(**payload),ensure_ascii=False))
    except (ValueError,KeyError,TypeError,AttributeError):parser.exit(1,'Analysis HTTP/reference verification failed.\n')
