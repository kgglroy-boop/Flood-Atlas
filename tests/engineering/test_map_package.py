import json
from pathlib import Path
import tempfile
import unittest
from osgeo import gdal
from tools.delivery.map_package import create_package
from tools.data.integrity import file_sha

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'data/processed/teaching-v1/74e68b2da680e9680f65'
class MapPackageTests(unittest.TestCase):
 def test_real_source_generates_six_correct_integrity_checked_views_without_source_mutation(self):
  before=file_sha(DATA/'manifest.json')
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'module';report=create_package(DATA,target)
   self.assertEqual(report['status'],'ok');self.assertEqual(file_sha(DATA/'manifest.json'),before)
   manifest=json.loads((target/'module.json').read_text());self.assertEqual(len(manifest['files']),8)
   for name,digest in manifest['files'].items():self.assertEqual(file_sha(target/name),digest)
   analyses=json.loads((target/'analysis.json').read_text())
   self.assertEqual(analyses['S02_T60']['summary']['affected_buildings'],91)
   self.assertEqual(analyses['S02_T60']['summary']['flooded_area_m2'],738775)
   for step in ['S01_T00','S02_T00']:
    image=gdal.Open(str(target/f'depth_{step}.png'));self.assertEqual(int(image.GetRasterBand(4).ReadAsArray().max()),0);image=None
   (target/'analysis.json').write_text('corrupt')
   with self.assertRaises(ValueError):create_package(DATA,target)

if __name__=='__main__':unittest.main()
