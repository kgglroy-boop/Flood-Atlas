import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.data.contract import load_contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'data/metadata/data-contract.json'


class ContractTests(unittest.TestCase):
    def test_frozen_metre_contract(self):
        c = load_contract(CONTRACT)
        self.assertEqual(c['analysis_srid'], 32650)
        self.assertEqual(c['units'], 'm')
        self.assertEqual((c['width'], c['height']), (404, 204))
        self.assertEqual(c['dataset_id'], 'teaching-v1')

    def test_rejects_wrong_crs_units_grid_and_steps(self):
        original = json.loads(CONTRACT.read_text(encoding='utf-8'))
        variants = [('analysis_srid', 4326), ('units', 'degrees'), ('width', 400),
                    ('nodata', 0), ('steps', [{'step_code': 'T15', 'time_min': 15}]),
                    ('scenarios', original['scenarios'][:1])]
        with tempfile.TemporaryDirectory() as tmp:
            for key, value in variants:
                with self.subTest(key=key):
                    changed = copy.deepcopy(original)
                    changed[key] = value
                    path = Path(tmp) / 'contract.json'
                    path.write_text(json.dumps(changed), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_contract(path)


if __name__ == '__main__':
    unittest.main()
