import tempfile
import unittest
from pathlib import Path
from osgeo import ogr,osr
from tools.engineering.reference import reference

class ReferenceTests(unittest.TestCase):
    def test_independent_qgis_planar_areas_and_released_handles(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'reference.gpkg'
            source=ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
            crs=osr.SpatialReference();crs.ImportFromEPSG(32650)
            layer=source.CreateLayer('buildings',crs,ogr.wkbPolygon)
            layer.CreateField(ogr.FieldDefn('building_id',ogr.OFTString))
            layer.CreateField(ogr.FieldDefn('name',ogr.OFTString));layer.CreateField(ogr.FieldDefn('usage',ogr.OFTString))
            for id,w in [('B001',10),('B108',20),('B200',30)]:
                feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('building_id',id)
                feature.SetGeometry(ogr.CreateGeometryFromWkt(f'POLYGON((500000 3400000,{500000+w} 3400000,{500000+w} 3400020,500000 3400020,500000 3400000))'))
                layer.CreateFeature(feature);feature=None
            layer=None;source=None
            self.assertEqual(reference(path)['building_areas_m2'],{'B001':200,'B108':400,'B200':600})
            path.rename(Path(temp)/'closed.gpkg')
