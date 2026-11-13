import unittest
from pathlib import Path

import numpy as np
from osgeo import ogr, osr

from tools.data.contract import load_contract
from tools.data.generation import build_assets, build_depths, wet_mask

CONTRACT = Path(__file__).resolve().parents[2] / 'data/metadata/data-contract.json'


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load_contract(CONTRACT)

    def test_threshold_precision_and_missing_values(self):
        a = np.array([0, .099, .100, .101, -9999], dtype=np.float32)
        np.testing.assert_array_equal(wet_mask(a, -9999, .1), [0, 0, 0, 1, 0])
        for invalid in [-.001, np.nan, np.inf, 2.001]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                wet_mask(np.array([invalid], dtype=np.float32), -9999, .1)

    def test_grid_and_dry_initial_step(self):
        arrays = build_depths(self.c)
        self.assertEqual(set(arrays), {(s, t) for s in ['S01', 'S02'] for t in [0, 30, 60]})
        for (scenario, minute), a in arrays.items():
            self.assertEqual(a.shape, (204, 404))
            self.assertEqual(a.dtype, np.dtype('float32'))
            self.assertEqual(int((a == -9999).sum()), 2416)
            self.assertEqual(int((a != -9999).sum()), 80000)
            self.assertTrue(np.all(a[:2, :] == -9999))
            self.assertTrue(np.all(a[-2:, :] == -9999))
            if minute == 0:
                self.assertTrue(np.all(a[2:-2, 2:-2] == 0))
        for scenario in ['S01', 'S02']:
            self.assertTrue(np.all(arrays[(scenario, 30)] <= arrays[(scenario, 60)]))
        for t in [0, 30, 60]:
            self.assertTrue(np.all(arrays[('S01', t)] <= arrays[('S02', t)]))
        self.assertAlmostEqual(float(arrays[('S01', 60)].max()), 1.189, places=5)
        self.assertAlmostEqual(float(arrays[('S02', 60)].max()), 1.783, places=5)

    def test_assets_are_unique_inside_and_nonoverlapping(self):
        assets = build_assets(self.c)
        self.assertEqual([len(assets[k]) for k in ['study_area', 'buildings', 'roads']], [1, 200, 32])
        study = assets['study_area'][0]['geom']
        self.assertAlmostEqual(study.GetArea(), 2_000_000)
        ids = [row['building_id'] for row in assets['buildings']]
        self.assertEqual(ids, [f'B{i:03d}' for i in range(1, 201)])
        collection = ogr.Geometry(ogr.wkbMultiPolygon)
        for row in assets['buildings']:
            g = row['geom']
            self.assertTrue(g.IsValid())
            self.assertTrue(study.Contains(g))
            self.assertAlmostEqual(g.GetArea(), 2400)
            collection.AddGeometry(g)
        self.assertAlmostEqual(collection.UnionCascaded().GetArea(), 200 * 2400)
        self.assertEqual(len({r['geom'].ExportToWkt() for r in assets['roads']}), 32)
        self.assertAlmostEqual(sum(r['geom'].Length() for r in assets['roads']), 43000)

    def test_projection_round_trip(self):
        a, b = osr.SpatialReference(), osr.SpatialReference()
        a.ImportFromEPSG(self.c['analysis_srid'])
        b.ImportFromEPSG(4326)
        for s in (a, b):
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lon, lat, _ = osr.CoordinateTransformation(a, b).TransformPoint(501000, 3400500)
        self.assertTrue(114 < lon < 120 and 0 < lat < 84)
        x, y, _ = osr.CoordinateTransformation(b, a).TransformPoint(lon, lat)
        self.assertLess(max(abs(x - 501000), abs(y - 3400500)), .001)


if __name__ == '__main__':
    unittest.main()
