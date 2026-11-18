import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from utils import file_ops


class ConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.original_config_file = file_ops.CONFIG_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        file_ops.CONFIG_FILE = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        file_ops.CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def test_legacy_slash_styles_are_read_as_one_folder(self):
        folder = os.path.join(self.temp_dir.name, "same", "folder")
        forward = folder.replace("\\", "/")
        with open(file_ops.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump(
                {
                    "recent_folders": [folder, forward],
                    "address_folders": [forward, folder],
                },
                config_file,
            )

        self.assertEqual(file_ops.get_recent_folders(), [os.path.normpath(folder)])
        self.assertEqual(file_ops.get_address_folders(), [os.path.normpath(folder)])

    def test_new_folder_writes_use_native_normalized_paths(self):
        folder = os.path.join(self.temp_dir.name, "new", "folder")
        forward = folder.replace("\\", "/")

        file_ops.add_recent_folder(forward)
        file_ops.add_address_folder(forward)
        config = file_ops.load_config()

        expected = os.path.normpath(os.path.abspath(folder))
        self.assertEqual(config["recent_folders"], [expected])
        self.assertEqual(config["address_folders"], [expected])

    def test_legacy_history_defaults_to_30_and_can_be_extended_before_next_use(self):
        folders = [os.path.join(self.temp_dir.name, str(n)) for n in range(45)]
        file_ops.save_config({"address_folders": folders[:20], "recent_folders": folders})
        self.assertEqual(file_ops.get_folder_history_limits(), (30, 30))
        self.assertEqual(file_ops.get_recent_folders(), folders[:30])
        self.assertEqual(file_ops.load_config()["recent_folders"], folders)

        file_ops.set_folder_history_limits(40, 45)
        for folder in reversed(folders):
            file_ops.add_address_folder(folder)
        self.assertEqual(file_ops.get_address_folders(), folders[:40])
        self.assertEqual(file_ops.get_recent_folders(), folders)
        file_ops.add_recent_folder(folders[-1])
        file_ops.set_folder_history_limits(2, 3)
        config = file_ops.load_config()
        self.assertEqual(config["address_folders"], folders[:2])
        self.assertEqual(config["recent_folders"], [folders[-1], *folders[:2]])

    def test_invalid_history_limits_fall_back_and_deduplication_precedes_eviction(self):
        first, second = [os.path.join(self.temp_dir.name, name) for name in ("one", "two")]
        file_ops.save_config({"address_folders_limit": False, "recent_folders_limit": "many",
                              "recent_folders": [first, first, "", second]})
        self.assertEqual(file_ops.get_folder_history_limits(), (30, 30))
        file_ops.set_folder_history_limits(1, 2)
        self.assertEqual(file_ops.get_recent_folders(), [first, second])
        file_ops.add_recent_folder(second)
        self.assertEqual(file_ops.get_recent_folders(), [second, first])

    def test_default_config_is_in_workspace_for_source_runs(self):
        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(file_ops.__file__))),
            "config.json",
        )
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(file_ops.default_config_file(), expected)

    def test_frozen_onedir_config_is_beside_executable(self):
        executable = os.path.join(
            self.temp_dir.name, "A5ImageViewer", "A5ImageViewer.exe"
        )
        expected = os.path.join(self.temp_dir.name, "A5ImageViewer", "config.json")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", executable),
        ):
            self.assertEqual(file_ops.default_config_file(), expected)

    def test_frozen_onefile_config_is_beside_executable(self):
        executable = os.path.join(self.temp_dir.name, "A5ImageViewer.exe")
        expected = os.path.join(self.temp_dir.name, "config.json")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", executable),
        ):
            self.assertEqual(file_ops.default_config_file(), expected)


if __name__ == "__main__":
    unittest.main()
