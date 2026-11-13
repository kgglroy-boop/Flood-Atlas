import unittest
from tools.delivery.video import validate_views

class VideoViews(unittest.TestCase):
 def test_required_views_cannot_be_replaced_by_main_only_samples(self):
  with self.assertRaises(ValueError):validate_views([{'view':'main'}]*200)
  validate_views([{'view':v} for v in ['main','mvt','evidence']])
