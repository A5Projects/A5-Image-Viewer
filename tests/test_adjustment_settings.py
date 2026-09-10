import os
import tempfile
import unittest

from utils import file_ops


class AdjustmentSettingsTests(unittest.TestCase):
    def setUp(self):
        self.original_config_file = file_ops.CONFIG_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        file_ops.CONFIG_FILE = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        file_ops.CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def test_values_persist_and_are_clamped(self):
        file_ops.set_adjustment_settings(True, {
            "Brightness": 12,
            "Contrast": -8,
            "Saturation": 500,
            "Shadows": -500,
            "Highlights": 4,
            "Gamma": 999,
            "Hue": -999,
            "Invert": True,
        })
        enabled, values = file_ops.get_adjustment_settings()
        self.assertTrue(enabled)
        self.assertEqual(values["Brightness"], 12)
        self.assertEqual(values["Saturation"], 100)
        self.assertEqual(values["Shadows"], -100)
        self.assertEqual(values["Gamma"], 300)
        self.assertEqual(values["Hue"], -180)
        self.assertTrue(values["Invert"])

    def test_disabling_clears_values(self):
        file_ops.set_adjustment_settings(True, {"Brightness": 40})
        file_ops.set_adjustment_settings(False)
        enabled, values = file_ops.get_adjustment_settings()
        self.assertFalse(enabled)
        for name, (_, _, default) in file_ops.ADJUSTMENT_LIMITS.items():
            self.assertEqual(values[name], default)
        self.assertTrue(
            all(not values[name] for name in file_ops.ADJUSTMENT_TOGGLE_NAMES)
        )
        self.assertNotIn("adjustment_values", file_ops.load_config())


if __name__ == "__main__":
    unittest.main()
