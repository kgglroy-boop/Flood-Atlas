"""Offline display module from verified science files and independent QGIS analysis."""
import argparse
import json
from pathlib import Path
import numpy as np
from osgeo import gdal,osr
from qgis.PyQt.QtGui import QImage
from tools.data.integrity import file_sha,read_json,atomic_json
from tools.data.contract import load_contract
from tools.data.validation import validate_dataset
from tools.data.project import PALETTE
from tools.analysis.reference import calculate_reference

def _transform(source,target):
 a=osr.SpatialReference();a.ImportFromEPSG(source);a.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
 b=osr.SpatialReference();b.ImportFromEPSG(target);b.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
 return osr.CoordinateTransformation(a,b)
def create_package(dataset:Path,output:Path)->dict:
 dataset=Path(dataset).resolve();output=Path(output)
 contract=load_contract(Path(__file__).resolve().parents[2]/'data/metadata/data-contract.json')
 valid=validate_dataset(dataset,contract);generation=read_json(dataset/'manifest.json')['generation_id']
 if output.exists():
  previous=read_json(output/'module.json')
  if previous['generation_id']!=generation or len(previous['files'])!=8 or any(file_sha(output/name)!=digest for name,digest in previous['files'].items()):raise ValueError('Existing map package differs; no overwrite performed')
  return dict(status='ok',output=str(output.resolve()),generation_id=generation,files=8,reused=True)
 output.mkdir(parents=True)
 reference=calculate_reference(dataset/'teaching.gpkg');analyses={};scenarios=[]
 for scenario,label in [('S01','教学情景A'),('S02','教学情景B')]:
  steps=[]
  for minute in (0,30,60):
   code=f'T{minute:02}';step=f'{scenario}_{code}'
   identity=dict(step_id=step,dataset_id='teaching-v1',generation_id=generation,model_type='synthetic_demo',analysis_srid=32650,threshold_m=.1)
   r=next(row for row in reference['steps'] if row['step_id']==step)
   summary=dict(**identity,flooded_area_m2=r['flooded_area_m2'],affected_buildings=len(r['affected_building_ids']),flooded_road_length_m=r['flooded_road_length_m'])
   features=[dict(type='Feature',id=b['building_id'],properties={k:b[k] for k in ['building_id','name','usage','affected']},geometry=b['geometry']) for b in r['buildings']]
   buildings=dict(type='FeatureCollection',features=features,metadata=dict(**identity,geometry_srid=4326,limit=200,returned_count=200,total_buildings=200,truncated=False))
   analyses[step]=dict(summary=summary,buildings=buildings)
   steps.append(dict(step_id=step,step_code=code,time_min=minute,layer_id=f'flood:depth_{step}'))
  scenarios.append(dict(scenario_id=scenario,name=label,steps=steps))
 catalog=dict(dataset_id='teaching-v1',generation_id=generation,model_type='synthetic_demo',analysis_srid=32650,depth_unit='m',threshold_m=.1,scenarios=scenarios)
 atomic_json(output/'catalog.json',catalog);atomic_json(output/'analysis.json',analyses)
 gdal.SetConfigOption('GDAL_PAM_ENABLED','NO');gdal.UseExceptions()
 image_coordinates=None
 xs=np.array([v for v,_ in PALETTE]);rgb=np.array([[int(c[i:i+2],16) for i in (1,3,5)] for _,c in PALETTE])
 for step in analyses:
  warped=gdal.Warp('',str(dataset/f'rasters/depth_{step}.tif'),format='MEM',dstSRS='EPSG:3857',resampleAlg='near',dstNodata=-9999)
  depth=warped.ReadAsArray();height,width=depth.shape;rgba=np.zeros((height,width,4),dtype=np.uint8)
  wet=(depth>np.float32(.1))&(depth!=-9999)
  for band in range(3):rgba[:,:,band]=np.rint(np.interp(depth,xs,rgb[:,band])).astype(np.uint8)
  rgba[:,:,3]=np.where(wet,255,0)
  image=QImage(rgba.tobytes(),width,height,width*4,QImage.Format_RGBA8888).copy()
  if not image.save(str(output/f'depth_{step}.png')):raise ValueError('Map display PNG failed')
  gt=warped.GetGeoTransform();west,north=gt[0],gt[3];east,south=west+width*gt[1],north+height*gt[5]
  transform=_transform(3857,4326)
  corners=[list(transform.TransformPoint(x,y)[:2]) for x,y in [(west,north),(east,north),(east,south),(west,south)]]
  if image_coordinates is not None and corners!=image_coordinates:raise ValueError('Display grids differ')
  image_coordinates=corners;warped=None
 transform=_transform(32650,4326);xmin,ymin,xmax,ymax=contract['study_bounds']
 outline=[list(transform.TransformPoint(x,y)[:2]) for x,y in [(xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax)]]
 bounds=[[min(p[0] for p in outline),min(p[1] for p in outline)],[max(p[0] for p in outline),max(p[1] for p in outline)]]
 files={p.name:file_sha(p) for p in sorted(output.iterdir())}
 atomic_json(output/'module.json',dict(version=1,id='teaching-snapshot',label='离线校验包',kind='package',generation_id=generation,bounds=bounds,outline=outline,image_coordinates=image_coordinates,files=files,provenance='QGIS independent planar analysis; nearest-neighbor display warp only; synthetic_demo',semantic_sha256=valid['semantic_sha256']))
 return dict(status='ok',output=str(output.resolve()),generation_id=generation,files=8,reused=False)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 print(json.dumps(create_package(a.dataset,a.output),ensure_ascii=False))
