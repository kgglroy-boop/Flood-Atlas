import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from osgeo import gdal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.wms.check_phase3 import validate_wms_png, validate_projected_png

gdal.UseExceptions()


class PngValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / 'depth.tif'
        self.values = np.array([[-9999, 0, .099], [.1, .101, 1.783]], dtype=np.float32)
        ds = gdal.GetDriverByName('GTiff').Create(str(self.reference), 3, 2, 1, gdal.GDT_Float32)
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(self.values)
        ds.Close()
        self.mask = (self.values != -9999) & (self.values > np.float32(.1))

    def png(self, alpha):
        path = self.root / 'map.png'
        ds = gdal.GetDriverByName('MEM').Create('', alpha.shape[1], alpha.shape[0], 4, gdal.GDT_Byte)
        for band in range(1, 4):
            ds.GetRasterBand(band).Fill(100)
        ds.GetRasterBand(4).WriteArray(alpha.astype(np.uint8))
        ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
        out = gdal.GetDriverByName('PNG').CreateCopy(str(path), ds)
        out.Close()
        ds.Close()
        return path

    def test_actual_png_alpha_matches_float32_threshold_and_nodata(self):
        report = validate_wms_png(self.png(self.mask * 255), self.reference)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['wet_pixel_count'], 2)
        self.assertEqual(report['transparent_pixel_count'], 4)

    def test_rejects_xml_and_broken_png_even_if_http_was_200(self):
        path = self.root / 'fake.png'
        for value in (b'<ServiceException>failed</ServiceException>', b'\x89PNG\r\n\x1a\ninvalid'):
            path.write_bytes(value)
            with self.assertRaises(ValueError):
                validate_wms_png(path, self.reference)

    def test_rejects_wrong_size(self):
        with self.assertRaises(ValueError):
            validate_wms_png(self.png(np.ones((3, 3)) * 255), self.reference)

    def test_dry_native_reference_requires_all_transparent(self):
        ds = gdal.Open(str(self.reference), gdal.GA_Update)
        ds.GetRasterBand(1).Fill(0)
        ds.Close()
        report = validate_wms_png(self.png(np.zeros_like(self.mask)), self.reference)
        self.assertEqual(report['wet_pixel_count'], 0)
        with self.assertRaises(ValueError):
            validate_wms_png(self.png(self.mask * 255), self.reference)

    def test_projected_empty_is_explicit_and_strict(self):
        empty = self.png(np.zeros_like(self.mask))
        self.assertEqual(validate_projected_png(empty, expected_empty=True)['visible_pixels'], 0)
        with self.assertRaises(ValueError): validate_projected_png(empty)
        wet = self.png(self.mask * 255)
        self.assertEqual(validate_projected_png(wet)['visible_pixels'], 2)
        with self.assertRaises(ValueError): validate_projected_png(wet, expected_empty=True)
        for content in (b'<ServiceException>failed</ServiceException>', b'\x89PNG\r\n\x1a\ninvalid'):
            wet.write_bytes(content)
            with self.assertRaises(ValueError): validate_projected_png(wet, expected_empty=True)

    def test_projected_png_without_alpha_is_rejected_even_for_dry_step(self):
        path = self.root / 'rgb.png'
        ds = gdal.GetDriverByName('MEM').Create('', 3, 2, 3, gdal.GDT_Byte)
        out = gdal.GetDriverByName('PNG').CreateCopy(str(path), ds)
        out.Close(); ds.Close()
        with self.assertRaises(ValueError): validate_projected_png(path, expected_empty=True)

    def test_rejects_all_transparent_shifted_and_dry_spill(self):
        spill = self.mask.copy()
        spill[1, 0] = True  # Float32(0.10) must remain transparent.
        for mask in (np.zeros_like(self.mask), np.roll(self.mask, 1, axis=1), spill):
            with self.assertRaises(ValueError):
                validate_wms_png(self.png(mask * 255), self.reference)


if __name__ == '__main__':
    unittest.main()
