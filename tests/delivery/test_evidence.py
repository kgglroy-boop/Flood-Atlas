import unittest
from tools.delivery.evidence import load_facts, validate_generation


class EvidenceFacts(unittest.TestCase):
    def test_actual_measurements_drive_display(self):
        facts = load_facts()
        self.assertEqual(facts['requests'], 2026)
        self.assertEqual(len(facts['steps']), 6)
        self.assertAlmostEqual(facts['hot'], 7.84, places=2)

    def test_mixed_generations_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_generation([{'generation_id': 'one'}, {'generation_id': 'two'}])
