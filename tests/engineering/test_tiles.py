import tempfile
import unittest
from pathlib import Path
from tools.engineering.check_tiles import check_tiles

class TileChecks(unittest.TestCase):
    def test_empty_tile_is_valid_but_cannot_hide_missing_buildings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'15/0/0.pbf';path.parent.mkdir(parents=True);path.write_bytes(b'')
            self.assertEqual(check_tiles(root,{})['empty_tiles'],1)
            with self.assertRaises(ValueError):check_tiles(root,{'B001':{'name':'demo','usage':'demo'}})
    def test_json_with_pbf_extension_is_not_a_vector_tile(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'15/0/0.pbf';path.parent.mkdir(parents=True)
            path.write_text('{"type":"FeatureCollection","features":[]}')
            with self.assertRaises(ValueError):check_tiles(root,{})
