"""Decode cache and uncached PNGs into comparable RGBA pixels."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from tools.wms.check_phase3 import read_png

def pixels(path):
    ds=read_png(Path(path))
    if (ds.RasterXSize,ds.RasterYSize)!=(256,256):raise ValueError('Invalid tile size')
    if ds.RasterCount==1 and ds.GetRasterBand(1).GetColorTable():
        table=ds.GetRasterBand(1).GetColorTable()
        colors=np.array([table.GetColorEntry(i) for i in range(table.GetCount())],dtype=np.uint8)
        result=colors[ds.GetRasterBand(1).ReadAsArray()]
    elif ds.RasterCount in (3,4):
        result=np.moveaxis(ds.ReadAsArray(),0,-1)
        if ds.RasterCount==3:result=np.concatenate([result,np.full((256,256,1),255,dtype=np.uint8)],axis=2)
    else:raise ValueError('Unsupported tile PNG')
    ds=None
    return result

def compare_tiles(cold,hot,wms):
    a,b,c=(pixels(p) for p in (cold,hot,wms))
    if not np.array_equal(a,b):raise ValueError('Cold/hot cached pixels differ')
    if not np.array_equal(a,c):raise ValueError('GWC and independent WMS pixels differ')
    return dict(status='ok',pixel_sha256=hashlib.sha256(a.tobytes()).hexdigest(),transparent_pixels=int(np.count_nonzero(a[:,:,3]==0)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cold',required=True);p.add_argument('--hot',required=True);p.add_argument('--wms',required=True)
    a=p.parse_args();print(json.dumps(compare_tiles(a.cold,a.hot,a.wms)))
