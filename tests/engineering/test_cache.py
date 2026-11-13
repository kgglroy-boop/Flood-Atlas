import tempfile
import unittest
from pathlib import Path
import numpy as np
from osgeo import gdal
from tools.engineering.check_cache import compare_tiles

class CacheTests(unittest.TestCase):
    def test_decodes_pixels_not_just_http_or_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            paths=[Path(temp)/f'{n}.png' for n in ('cold','hot','wms')]
            source=gdal.GetDriverByName('MEM').Create('',256,256,4,gdal.GDT_Byte)
            for band in range(1,5):source.GetRasterBand(band).WriteArray(np.full((256,256),band*30,dtype=np.uint8))
            for path in paths:gdal.GetDriverByName('PNG').CreateCopy(str(path),source)
            self.assertEqual(compare_tiles(*paths)['status'],'ok')
            source.GetRasterBand(1).WriteArray(np.zeros((256,256),dtype=np.uint8))
            gdal.GetDriverByName('PNG').CreateCopy(str(paths[1]),source)
            with self.assertRaises(ValueError):compare_tiles(*paths)
            paths[1].write_text('<ExceptionReport/>')
            with self.assertRaises(ValueError):compare_tiles(*paths)
