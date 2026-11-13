import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

from tools.data.contract import load_contract
from tools.data.raster import polygonize_wet
from tools.data.artifacts import generate_dataset
from tools.data.validation import validate_dataset
from tools.data.integrity import file_sha, read_json, atomic_json

CONTRACT = Path(__file__).resolve().parents[2] / 'data/metadata/data-contract.json'


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='phase2-validation-tests-')
        cls.root = Path(cls.tmp.name)
        cls.contract = load_contract(CONTRACT)
        cls.source = generate_dataset(CONTRACT, cls.root / 'source', cls.root / 'source.csv')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_four_connected_polygons_and_empty(self):
        g = polygonize_wet(np.array([[1, 0], [0, 1]], dtype=np.float32), self.contract)
        self.assertEqual(g.GetGeometryName(), 'MULTIPOLYGON')
        self.assertEqual(g.GetGeometryCount(), 2)
        self.assertAlmostEqual(g.GetArea(), 50)
        g = polygonize_wet(np.array([[1, 1], [0, 0]], dtype=np.float32), self.contract)
        self.assertEqual(g.GetGeometryCount(), 1)
        self.assertTrue(polygonize_wet(np.zeros((2, 2), dtype=np.float32), self.contract).IsEmpty())

    def test_rejects_tampered_grid_values_crs_missing_file_or_ids(self):
        for kind in ['grid', 'negative', 'crs', 'missing', 'duplicate']:
            with self.subTest(kind=kind):
                target = self.root / kind
                shutil.copytree(self.source, target)
                path = target / 'rasters/depth_S01_T30.tif'
                if kind == 'missing':
                    path.unlink()
                elif kind == 'duplicate':
                    ds = ogr.Open(str(target / 'teaching.gpkg'), 1)
                    layer = ds.GetLayerByName('buildings')
                    feature = layer.GetFeature(2)
                    feature.SetField('building_id', 'B001')
                    layer.SetFeature(feature)
                    feature, layer, ds = None, None, None
                else:
                    ds = gdal.Open(str(path), gdal.GA_Update)
                    if kind == 'grid':
                        ds.SetGeoTransform((499991, 5, 0, 3401010, 0, -5))
                    elif kind == 'crs':
                        ds.SetProjection('EPSG:4326')
                    else:
                        a = ds.ReadAsArray()
                        a[10, 10] = -1
                        ds.GetRasterBand(1).WriteArray(a)
                    ds = None
                if kind != 'missing':
                    manifest = read_json(target / 'manifest.json')
                    modified = 'teaching.gpkg' if kind == 'duplicate' else 'rasters/depth_S01_T30.tif'
                    manifest['files'][modified] = file_sha(target / modified)
                    atomic_json(target / 'manifest.json', manifest)
                with self.assertRaises((ValueError, RuntimeError)):
                    validate_dataset(target, self.contract)


if __name__ == '__main__':
    unittest.main()
