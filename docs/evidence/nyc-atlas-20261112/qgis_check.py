import json
import os
from pathlib import Path

import numpy as np
from osgeo import gdal
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsGeometry, QgsProject, QgsSpatialIndex, QgsVectorLayer)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app=QgsApplication([],False)
app.initQgis()
source=Path("data/processed/cases/nyc-ida")
work=Path("work/nyc-final-20261112")
project=QgsProject.instance()
target=QgsCoordinateReferenceSystem("EPSG:32618")

def vectors(name):
    layer=QgsVectorLayer(str((source/(name+".geojson")).resolve()),name,"ogr")
    assert layer.isValid()
    transform=QgsCoordinateTransform(layer.crs(),target,project)
    index=QgsSpatialIndex()
    items={}
    for feature in layer.getFeatures():
        if name=="water" and not feature["permanent_water"]:
            continue
        geometry=feature.geometry()
        if not geometry.isGeosValid(): geometry=geometry.makeValid()
        geometry.transform(transform)
        record=QgsFeature(feature.id())
        record.setGeometry(geometry)
        index.addFeature(record)
        items[feature.id()]=(str(feature["id"]),geometry)
    return index,items

def extent(path,threshold,water_index,water):
    raster=gdal.Open(str(path))
    band=raster.GetRasterBand(1)
    depth=band.ReadAsArray()
    mask=np.isfinite(depth)&(band.GetMaskBand().ReadAsArray()!=0)&(depth>np.float32(threshold))
    x,dx,_,y,_,dy=raster.GetGeoTransform()
    from qgis.core import QgsPointXY,QgsRectangle
    cells=[]
    for j,i in zip(*np.where(mask),strict=True):
        cx,cy=x+(i+.5)*dx,y+(j+.5)*dy
        point=QgsGeometry.fromPointXY(QgsPointXY(cx,cy))
        if any(water[fid][1].intersects(point) for fid in water_index.intersects(QgsRectangle(cx,cy,cx,cy))):
            continue
        cells.append(QgsGeometry.fromRect(QgsRectangle(x+i*dx,y+(j+1)*dy,x+(i+1)*dx,y+j*dy)))
    return QgsGeometry.unaryUnion(cells),len(cells)*dx*abs(dy)

bindex,buildings=vectors("buildings")
rindex,roads=vectors("roads")
windex,water=vectors("water")
case=json.loads(Path("data/processed/case-library/catalog.json").read_text(encoding="utf-8"))
case=next(item for item in case["cases"] if item["id"]=="nyc-ida")
rows=[]
for suffix,frame in zip((2,4,5),case["steps"],strict=True):
    wet,area=extent(source/f"depth{suffix:02d}.tif",case["threshold_m"],windex,water)
    polygons=list(wet.asGeometryCollection()) or [wet]
    ids=set()
    pieces=[]
    for part in polygons:
        engine=QgsGeometry.createGeometryEngine(part.constGet())
        engine.prepareGeometry()
        bbox=part.boundingBox()
        for fid in bindex.intersects(bbox):
            bid,geometry=buildings[fid]
            if bid not in ids and engine.intersects(geometry.constGet()) and geometry.intersection(part).area()>0:
                ids.add(bid)
        for fid in rindex.intersects(bbox):
            geometry=roads[fid][1]
            if engine.intersects(geometry.constGet()):
                intersection=geometry.intersection(part)
                if not intersection.isEmpty(): pieces.append(intersection)
    length=QgsGeometry.unaryUnion(pieces).length()
    rows.append({"id":frame["id"],"area_m2":area,"building_count":len(ids),"road_length_m":round(length,2),
                 "affected_ids":sorted(ids),"service":frame["summary"]})
(work/"qgis-checks.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
print([(row["id"],row["area_m2"],row["building_count"],row["road_length_m"]) for row in rows],flush=True)
os._exit(0)
