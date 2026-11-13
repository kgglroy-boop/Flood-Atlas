"""Small explicit GeoPackage schemas and WKB transport records."""

from pathlib import Path

from osgeo import ogr

from .contract import spatial_reference

FIELDS = {
    'study_area': {'area_id': ogr.OFTString, 'dataset_id': ogr.OFTString, 'name': ogr.OFTString},
    'buildings': {'building_id': ogr.OFTString, 'dataset_id': ogr.OFTString,
                  'name': ogr.OFTString, 'usage': ogr.OFTString},
    'roads': {'road_id': ogr.OFTString, 'dataset_id': ogr.OFTString,
              'name': ogr.OFTString, 'direction': ogr.OFTString},
    'flood_extents': {'scenario_id': ogr.OFTString, 'time_min': ogr.OFTInteger,
                      'wet_pixel_count': ogr.OFTInteger, 'area_m2': ogr.OFTReal, 'threshold_m': ogr.OFTReal},
}
TYPES = {'study_area': ogr.wkbMultiPolygon, 'buildings': ogr.wkbPolygon,
         'roads': ogr.wkbLineString, 'flood_extents': ogr.wkbMultiPolygon}


def write_geopackage(path: Path, layers: dict[str, list[dict]]) -> None:
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    for name, fields in FIELDS.items():
        layer = ds.CreateLayer(name, spatial_reference(), TYPES[name], options=['SPATIAL_INDEX=YES'])
        for key, field_type in fields.items():
            layer.CreateField(ogr.FieldDefn(key, field_type))
        layer.StartTransaction()
        for row in layers[name]:
            feature = ogr.Feature(layer.GetLayerDefn())
            for key in fields:
                feature.SetField(key, row[key])
            feature.SetGeometry(row['geom'])
            layer.CreateFeature(feature)
            feature = None
        layer.CommitTransaction()
        layer = None
    ds = None


def read_geopackage(path: Path) -> dict[str, list[dict]]:
    ds = ogr.Open(str(path), 0)
    if ds is None:
        raise ValueError('Cannot open teaching GeoPackage.')
    result = {}
    for name in FIELDS:
        layer = ds.GetLayerByName(name)
        if layer is None or layer.GetSpatialRef().GetAuthorityCode(None) != '32650':
            raise ValueError(f'GeoPackage layer missing or wrong CRS: {name}')
        result[name] = []
        for feature in layer:
            geom = feature.GetGeometryRef()
            if geom is None:
                raise ValueError(f'NULL geometry in {name}')
            row = {key: feature.GetField(key) for key in FIELDS[name]}
            row['geom'] = geom.Clone()
            result[name].append(row)
        layer = None
    ds = None
    return result


def transport_rows(rows: list[dict]) -> list[dict]:
    return [{**{k: v for k, v in r.items() if k != 'geom'},
             'geom_wkb_hex': bytes(r['geom'].Normalize().ExportToWkb(ogr.wkbNDR)).hex()} for r in rows]
