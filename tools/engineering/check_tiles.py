"""Decode actual MVT and compare application properties with independent GPKG."""
import argparse
import json
import urllib.request
from pathlib import Path
from osgeo import gdal
from qgis.core import QgsWkbTypes
from tools.analysis.reference import _init,_load

gdal.UseExceptions()

def download_tiles(root:Path,port:int):
    if port not in (8000,5173) or list(root.glob('*/*/*.pbf')):raise ValueError('Refusing target or overwrite')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for x in range(27032,27037):
        for y in range(13440,13445):
            with opener.open(f'http://127.0.0.1:{port}/api/v1/tiles/buildings/15/{x}/{y}.pbf',timeout=10) as response:
                if response.status!=200 or response.headers.get_content_type()!='application/vnd.mapbox-vector-tile' or response.headers.get('Cache-Control')!='no-store':raise ValueError('Invalid MVT HTTP contract')
                content=response.read(4*1024*1024+1)
                if len(content)>4*1024*1024:raise ValueError('Unbounded tile response')
            path=root/'15'/str(x)/f'{y}.pbf';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)

def check_tiles(root:Path,expected:dict)->dict:
    seen=set();empty=0;total=0
    for path in sorted(Path(root).glob('*/*/*.pbf')):
        total+=1
        if not path.stat().st_size:empty+=1;continue
        z,x,y=map(int,(path.parent.parent.name,path.parent.name,path.stem))
        if not 0<=z<=19 or not 0<=x<2**z or not 0<=y<2**z:raise ValueError('Invalid XYZ file path')
        try:source=gdal.OpenEx(str(path),gdal.OF_VECTOR,allowed_drivers=['MVT'],open_options=['CLIP=NO'])
        except RuntimeError:raise ValueError('Tile is not decodable MVT') from None
        if source is None or source.GetLayerCount()!=1:raise ValueError('Invalid MVT layer count')
        layer=source.GetLayerByName('buildings')
        if layer is None:raise ValueError('Missing MVT buildings layer')
        fields={layer.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(layer.GetLayerDefn().GetFieldCount())}
        if not {'building_id','name','usage'}<=fields or fields-{'building_id','name','usage','mvt_id'}:raise ValueError('Unexpected MVT attributes')
        world=40075016.68557849;size=world/2**z;half=world/2;pad=size*64/4096
        bounds=(-half+x*size-pad,-half+(x+1)*size+pad,half-(y+1)*size-pad,half-y*size+pad)
        for feature in layer:
            id=feature.GetField('building_id');geometry=feature.GetGeometryRef()
            if id not in expected or any(feature.GetField(k)!=expected[id][k] for k in ('name','usage')):raise ValueError('MVT properties differ from independent source')
            if geometry is None or geometry.IsEmpty() or not geometry.IsValid():raise ValueError('Invalid clipped MVT geometry')
            extent=geometry.GetEnvelope()
            if any(v<lo-1e-5 or v>hi+1e-5 for v,lo,hi in ((extent[0],bounds[0],bounds[1]),(extent[1],bounds[0],bounds[1]),(extent[2],bounds[2],bounds[3]),(extent[3],bounds[2],bounds[3]))):raise ValueError('MVT exceeds buffered tile bounds')
            seen.add(id)
        feature=None;layer=None;source=None
    if not total or seen!=set(expected):raise ValueError('MVT unique ID set is incomplete')
    return dict(status='ok',tile_count=total,empty_tiles=empty,unique_buildings=len(seen),building_ids=sorted(seen),extent=4096,buffer=64)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--gpkg',type=Path,required=True)
    p.add_argument('--download',action='store_true');p.add_argument('--port',type=int,choices=[8000,5173],default=8000)
    args=p.parse_args();_init()
    rows=_load(args.gpkg,'buildings',QgsWkbTypes.PolygonGeometry,['building_id','name','usage'])
    expected={r['building_id']:{k:r[k] for k in ('name','usage')} for r,_g in rows}
    if len(expected)!=200:raise SystemExit('Independent building count is not200')
    if args.download:download_tiles(args.root,args.port)
    print(json.dumps(check_tiles(args.root,expected)))
