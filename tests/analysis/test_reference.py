import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.analysis.reference import calculate_reference
from gis_fixtures import write_micro_gpkg


class ReferenceTests(unittest.TestCase):
    def test_hand_calculated_six_steps_and_complete_building(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'micro.gpkg';write_micro_gpkg(path)
            report=calculate_reference(path)
            self.assertEqual(report['status'],'ok');self.assertEqual(len(report['steps']),6)
            for step in report['steps']:
                if step['step_id'].endswith('T00'):
                    self.assertEqual(step['flooded_area_m2'],0)
                    self.assertEqual(step['affected_building_ids'],[])
                    self.assertEqual(step['flooded_road_length_m'],0)
                else:
                    self.assertEqual(step['flooded_area_m2'],150)
                    self.assertEqual(step['affected_building_ids'],['B001','B002','B003'])
                    self.assertEqual(step['flooded_road_length_m'],30)
                geometry=step['buildings'][1]['geometry']
                self.assertEqual(geometry['type'],'Polygon')
                ring=geometry['coordinates'][0]
                self.assertEqual(len(ring),5)
                self.assertTrue(all(116<x<118 and 30<y<32 for x,y in ring))
                self.assertGreater(max(x for x,y in ring)-min(x for x,y in ring),0)

    def test_wrong_crs_and_missing_layers_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.gpkg';write_micro_gpkg(path,4326)
            with self.assertRaises(ValueError):calculate_reference(path)
            with self.assertRaises(ValueError):calculate_reference(Path(temp)/'missing.gpkg')


if __name__=='__main__':unittest.main()
