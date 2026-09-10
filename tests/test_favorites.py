import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils import file_ops


class FavoriteDisplayNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_config_file = file_ops.CONFIG_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        file_ops.CONFIG_FILE = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        file_ops.CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def test_custom_display_name_persists_without_changing_path(self):
        folder = os.path.join(self.temp_dir.name, "long-folder-name")
        os.mkdir(folder)
        file_ops.add_favorite_folder(folder)
        file_ops.set_favorite_display_name(folder, "Short name")

        self.assertEqual(file_ops.get_favorite_folders(), [os.path.abspath(folder)])
        self.assertEqual(file_ops.get_favorite_display_name(folder), "Short name")

    def test_removing_favorite_cleans_display_name(self):
        folder = os.path.join(self.temp_dir.name, "folder")
        os.mkdir(folder)
        file_ops.add_favorite_folder(folder)
        file_ops.set_favorite_display_name(folder, "Alias")
        file_ops.remove_favorite_folder(folder)

        self.assertEqual(file_ops.get_favorite_folders(), [])
        self.assertEqual(file_ops.get_favorite_display_name(folder), "")

    def test_favorite_sort_setting_persists_and_is_removed_with_favorite(self):
        folder = os.path.join(self.temp_dir.name, "folder")
        non_favorite = os.path.join(self.temp_dir.name, "other")
        os.mkdir(folder)
        os.mkdir(non_favorite)
        file_ops.add_favorite_folder(folder)

        file_ops.set_favorite_sort_setting(folder, "date", True)
        file_ops.set_favorite_sort_setting(non_favorite, "type", True)

        self.assertEqual(
            file_ops.get_favorite_sort_setting(folder), ("date", True)
        )
        self.assertIsNone(file_ops.get_favorite_sort_setting(non_favorite))

        file_ops.remove_favorite_folder(folder)
        self.assertIsNone(file_ops.get_favorite_sort_setting(folder))

    def test_main_window_restores_favorite_sort_control(self):
        folder = os.path.join(self.temp_dir.name, "folder")
        os.mkdir(folder)
        file_ops.add_favorite_folder(folder)
        file_ops.set_favorite_sort_setting(folder, "date", True)

        window = MainWindow()
        try:
            window.restore_favorite_sort_setting(folder)
            self.assertEqual((window.sort_key, window.sort_reverse), ("date", True))
            self.assertEqual(window.sort_combo.currentData(), ("date", True))
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_favorite_row_uses_alias_and_full_path_tooltip(self):
        folder = os.path.join(self.temp_dir.name, "folder")
        os.mkdir(folder)
        file_ops.add_favorite_folder(folder)
        file_ops.set_favorite_display_name(folder, "Alias")
        window = MainWindow()
        try:
            item = window.favorites_list.item(0)
            self.assertEqual(item.text(), "Alias")
            self.assertEqual(item.toolTip(), os.path.abspath(folder))
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()


if __name__ == "__main__":
    unittest.main()
