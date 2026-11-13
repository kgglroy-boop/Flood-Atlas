"""Read-only QGIS reference calculation from the original GeoPackage."""
import argparse
import json
import math
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from osgeo import ogr, gdal

gdal.UseExceptions()
from qgis.core import (QgsApplication,QgsGeometry,QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,QgsProject,QgsWkbTypes)

_APP=None


def _init():
    global _APP
    if QgsApplication.instance() is None:
        _APP=QgsApplication([],False);_APP.initQgis()


def _load(path, name, shape, fields, allow_empty=False):
    # GDAL's explicit read-only handle avoids QGIS OGR provider connection pooling
    # holding the Windows source file open after the reference calculation.
    source=ogr.Open(str(path),0)
    if source is None:raise ValueError('Reference GeoPackage unavailable')
    layer=None;feature=None
    try:
        layer=source.GetLayerByName(name)
        if layer is None or layer.GetSpatialRef() is None or layer.GetSpatialRef().GetAuthorityCode(None)!='32650':
            raise ValueError('Reference layer or CRS unavailable')
        if any(layer.GetLayerDefn().GetFieldIndex(key)<0 for key in fields):raise ValueError('Reference fields unavailable')
        rows=[]
        for feature in layer:
            native=feature.GetGeometryRef()
            if native is None:raise ValueError('Missing reference geometry')
            geometry=QgsGeometry()
            geometry.fromWkb(bytes(native.ExportToWkb()))
            if geometry.isNull() or geometry.type()!=shape or (geometry.isEmpty() and not allow_empty) or not geometry.isGeosValid():
                raise ValueError('Invalid reference geometry')
            if any(not math.isfinite(p.x()) or not math.isfinite(p.y()) for p in geometry.vertices()):
                raise ValueError('Nonfinite reference geometry')
            rows.append(({key:feature.GetField(key) for key in fields},geometry))
        if not rows:raise ValueError('Empty reference layer')
        return rows
    finally:
        feature=None;layer=None;source=None


def _line_length(geometry):
    if geometry.isEmpty():return 0.0
    if geometry.type()==QgsWkbTypes.LineGeometry:return geometry.length()
    if geometry.type()==QgsWkbTypes.UnknownGeometry:
        return sum(_line_length(part) for part in geometry.asGeometryCollection())
    return 0.0


def calculate_reference(gpkg_path:Path)->dict:
    _init()
    if not Path(gpkg_path).is_file():raise ValueError('Reference GeoPackage unavailable')
    _load(gpkg_path,'study_area',QgsWkbTypes.PolygonGeometry,['area_id'])
    buildings=_load(gpkg_path,'buildings',QgsWkbTypes.PolygonGeometry,['building_id','name','usage'])
    roads=_load(gpkg_path,'roads',QgsWkbTypes.LineGeometry,['road_id'])
    extents=_load(gpkg_path,'flood_extents',QgsWkbTypes.PolygonGeometry,['scenario_id','time_min'],True)
    buildings.sort(key=lambda row:row[0]['building_id'])
    if len({row[0]['building_id'] for row in buildings})!=len(buildings) or len({row[0]['road_id'] for row in roads})!=len(roads):
        raise ValueError('Duplicate reference IDs')
    expected={f'{s}_T{t:02}' for s in ('S01','S02') for t in (0,30,60)}
    grouped={}
    for attributes,geometry in extents:
        step_id=f"{attributes['scenario_id']}_T{int(attributes['time_min']):02}"
        if step_id not in expected:raise ValueError('Unknown reference step')
        grouped.setdefault(step_id,[]).append(geometry)
    if set(grouped)!=expected:raise ValueError('Incomplete reference steps')
    transform=QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:32650'),QgsCoordinateReferenceSystem('EPSG:4326'),QgsProject.instance())
    public_buildings=[]
    for attributes,geometry in buildings:
        transformed=QgsGeometry(geometry)
        if transformed.transform(transform)!=0:raise ValueError('Reference transform failed')
        public_buildings.append(dict(**attributes,geometry=json.loads(transformed.asJson(9))))
    steps=[]
    for step_id,parts in sorted(grouped.items()):
        wet_parts=[g for g in parts if not g.isEmpty()]
        wet=QgsGeometry.unaryUnion(wet_parts) if wet_parts else QgsGeometry.fromWkt('MULTIPOLYGON EMPTY')
        if wet.isNull() or not wet.isGeosValid():raise ValueError('Reference union failed')
        affected=[attributes['building_id'] for attributes,g in buildings if wet.intersects(g)]
        length=sum(_line_length(g.intersection(wet)) for _,g in roads if g.intersects(wet))
        features=[dict(**b,affected=b['building_id'] in affected) for b in public_buildings]
        steps.append(dict(step_id=step_id,flooded_area_m2=wet.area(),affected_building_ids=affected,
                          flooded_road_length_m=length,buildings=features))
    return dict(status='ok',analysis_srid=32650,steps=steps)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpkg',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(calculate_reference(args.gpkg),ensure_ascii=False))
    except (ValueError,RuntimeError):
        parser.exit(1,'Reference calculation failed; source files were not modified.\n')
