import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication

from main import startup_path_from_arguments
from tests.qt_wait import wait_until
from ui.main_window import MainWindow
from utils import file_ops


class StartupActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(config_dir.cleanup)
        config = patch.object(file_ops, "CONFIG_FILE", os.path.join(config_dir.name, "config.json"))
        config.start()
        self.addCleanup(config.stop)

    def test_closing_before_startup_cancels_delayed_folder_open(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(startup_path=folder)
            with patch.object(window, "open_startup_path") as open_path:
                window.close()
                self.app.processEvents()
                open_path.assert_not_called()

    def test_argument_parser_returns_first_existing_path(self):
        with tempfile.TemporaryDirectory() as folder:
            image_path = os.path.join(folder, "image with spaces.png")
            Image.new("RGB", (4, 4), "red").save(image_path)

            result = startup_path_from_arguments(
                [os.path.join(folder, "missing.png"), f'"{image_path}"']
            )

            self.assertEqual(result, os.path.abspath(image_path))

    def test_open_startup_image_selects_and_opens_it(self):
        with tempfile.TemporaryDirectory() as folder:
            image_path = os.path.join(folder, "startup.png")
            Image.new("RGB", (8, 6), "blue").save(image_path)
            window = MainWindow(startup_path=image_path)
            try:
                self.assertTrue(window.open_startup_path(image_path))
                wait_until(lambda: not window.thumbnail_view.loading)
                self.assertEqual(
                    os.path.normpath(window.current_folder_path),
                    os.path.normpath(folder),
                )
                self.assertEqual(
                    os.path.normcase(os.path.normpath(window.current_image_path)),
                    os.path.normcase(os.path.normpath(image_path)),
                )
                self.assertEqual(window.current_item_kind, "image")
                self.assertEqual(
                    os.path.normcase(os.path.normpath(
                        window.fullscreen_viewer.current_image_path
                    )),
                    os.path.normcase(os.path.normpath(image_path)),
                )
            finally:
                window.fullscreen_viewer.close()
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_open_startup_folder_does_not_require_an_image(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(startup_path=folder)
            try:
                self.assertTrue(window.open_startup_path(folder))
                self.assertEqual(
                    os.path.normpath(window.current_folder_path),
                    os.path.normpath(folder),
                )
                self.assertEqual(window.windowTitle(), os.path.basename(folder))
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_window_title_uses_folder_name_and_drive_root(self):
        window = MainWindow()
        try:
            self.assertEqual(window.folder_window_title(None), "A5ImageViewer")
            self.assertEqual(
                window.folder_window_title("C:/Pictures/Exports"),
                "Exports",
            )
            self.assertEqual(window.folder_window_title("C:/"), "C:")
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()


if __name__ == "__main__":
    unittest.main()
