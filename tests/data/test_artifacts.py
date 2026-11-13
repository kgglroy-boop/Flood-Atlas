import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from tools.data.artifacts import generate_dataset, resolve_latest
from tools.data.validation import validate_dataset
from tools.data.contract import load_contract

CONTRACT = Path(__file__).resolve().parents[2] / 'data/metadata/data-contract.json'


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='phase2-gis-tests-')
        cls.root = Path(cls.tmp.name)
        cls.first = generate_dataset(CONTRACT, cls.root / 'one', cls.root / 'sources1.csv')
        cls.second = generate_dataset(CONTRACT, cls.root / 'two', cls.root / 'sources2.csv')
        cls.contract = load_contract(CONTRACT)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_actual_products_and_repeatable_semantic_content(self):
        one = validate_dataset(self.first, self.contract)
        two = validate_dataset(self.second, self.contract)
        self.assertEqual(one['semantic_sha256'], two['semantic_sha256'])
        self.assertEqual(one['counts'], {'study_area': 1, 'buildings': 200, 'roads': 32, 'flood_extents': 6})
        self.assertEqual(len(list((self.first / 'rasters').glob('*.tif'))), 6)
        self.assertTrue(all(r['area_m2'] == r['wet_pixel_count'] * 25 for r in one['rasters']))
        self.assertTrue(all(r['wet_pixel_count'] == 0 for r in one['rasters'] if r['time_min'] == 0))
        self.assertGreater(one['rasters'][-1]['wet_pixel_count'], 0)

    def test_reuses_only_verified_complete_products(self):
        self.assertEqual(generate_dataset(CONTRACT, self.root / 'one', self.root / 'sources1.csv'), self.first)
        with ZipFile(self.first / 'teaching-review.qgz') as archive:
            text = archive.read(next(n for n in archive.namelist() if n.endswith('.qgs'))).decode('utf-8')
            self.assertIn('32650', text)
            self.assertIn('depth_S02_T60', text)
            self.assertNotIn('http://', text.split('<projectlayers>')[-1].split('</projectlayers>')[0])
        self.assertGreater((self.first / 'teaching-atlas.png').stat().st_size, 10000)

    def test_failed_generation_leaves_old_pointer_and_partial_files(self):
        root = self.root / 'failure'
        root.mkdir()
        old = root / 'old'
        old.mkdir()
        pointer = {'generation_id': 'old', 'relative_path': 'old'}
        (root / 'latest.json').write_text(json.dumps(pointer), encoding='utf-8')
        with patch('tools.data.artifacts.write_depth', side_effect=OSError('simulated disk error')):
            with self.assertRaises(OSError):
                generate_dataset(CONTRACT, root, self.root / 'failed-source.csv')
        self.assertEqual(json.loads((root / 'latest.json').read_text()), pointer)
        with self.assertRaises(ValueError):
            generate_dataset(CONTRACT, root, self.root / 'failed-source.csv')

    def test_pointer_escape_is_rejected(self):
        root = self.root / 'escape'
        root.mkdir()
        (root / 'latest.json').write_text('{"relative_path":"../external"}')
        with self.assertRaises(ValueError):
            resolve_latest(root)

    def test_modified_product_is_never_reused(self):
        root = self.root / 'modified'
        shutil.copytree(self.first.parent, root)
        with (root / self.first.name / 'rasters/depth_S01_T30.tif').open('ab') as stream:
            stream.write(b'changed')
        before = (root / 'latest.json').read_bytes()
        with self.assertRaises(ValueError):
            generate_dataset(CONTRACT, root, self.root / 'modified.csv')
        self.assertEqual((root / 'latest.json').read_bytes(), before)

    def test_atlas_has_visible_titles_not_only_maps(self):
        from qgis.PyQt.QtGui import QImage, QColor
        image = QImage(str(self.first / 'teaching-atlas.png'))
        background = QColor('#f0f4f5').rgba()
        ink = sum(image.pixel(x, y) != background
                  for x in range(64, 1500, 3) for y in range(30, 235, 3))
        self.assertGreater(ink, 500, 'Atlas heading and provenance text must be visible.')


if __name__ == '__main__':
    unittest.main()
