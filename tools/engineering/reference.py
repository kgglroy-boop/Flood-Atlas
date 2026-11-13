"""Independent QGIS planar areas from the frozen GeoPackage."""
import argparse
import json
from pathlib import Path
from qgis.core import QgsWkbTypes
from tools.analysis.reference import _init,_load

def reference(path:Path)->dict:
    _init()
    rows=_load(path,'buildings',QgsWkbTypes.PolygonGeometry,['building_id','name','usage'])
    wanted={'B001','B108','B200'}
    areas={p['building_id']:g.area() for p,g in rows if p['building_id'] in wanted}
    if set(areas)!=wanted:raise ValueError('Missing independent sample buildings')
    return dict(status='ok',analysis_srid=32650,building_areas_m2=areas)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--gpkg',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(reference(args.gpkg)))
