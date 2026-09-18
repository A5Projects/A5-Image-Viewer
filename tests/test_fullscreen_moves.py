import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.thumbnail_view import PATH_ROLE
from ui.transfer_conflicts import TransferJob, scan_transfer_job
from utils import file_ops


class FullscreenMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.folder = os.path.join(self.temp.name, "source").replace("\\", "/")
        self.destination = os.path.join(self.temp.name, "destination")
        os.mkdir(self.folder)
        os.mkdir(self.destination)
        self.paths = []
        for name, color in zip(("a.png", "b.png", "c.png", "d.png"), ("red", "green", "blue", "yellow")):
            path = os.path.join(self.folder, name)
            Image.new("RGB", (8, 6), color).save(path)
            self.paths.append(path)
        self.window = MainWindow()
        self.app.processEvents()
        self.window.current_folder_path = self.folder
        self.window.thumbnail_view.load_folder(self.folder, show_folders=False)
        self.window.select_image_by_path(self.paths[1])
        self.window.fullscreen_start_path = self.paths[1]
        self.window.fullscreen_viewer.load_image(self.paths[1])

    def tearDown(self):
        self.window.fullscreen_viewer.close()
        self.window.transfer_coordinator.shutdown()
        self.window.thumbnail_view.shutdown()
        self.window.crop_prefetch_service.shutdown()
        # Deliver queued prefetch signals while their QObject receivers still live.
        self.app.processEvents()
        self.window.close()
        self.config_patch.stop()
        self.temp.cleanup()

    def move(self, paths, perform=True):
        job = TransferJob(1, paths, self.destination, move_files=True)
        plan = scan_transfer_job(job)

        def operation(pairs, **kwargs):
            if not perform:
                return None
            for source, target in pairs:
                shutil.move(source, target)
            return True

        with patch("ui.main_window.move_file_pairs", side_effect=operation):
            self.window.transfer_coordinator._process_plan(plan)

    def test_move_advances_fullscreen_and_browser_with_mixed_slashes(self):
        self.move([self.paths[1]])
        self.assertFalse(os.path.exists(self.paths[1]))
        self.assertTrue(os.path.exists(os.path.join(self.destination, "b.png")))
        self.assertIsNone(self.window.row_for_path(self.paths[1]))
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[2])
        self.assertEqual(self.window.thumbnail_view.currentIndex().data(PATH_ROLE), self.paths[2])
        pixel = self.window.fullscreen_viewer.viewer.pixmap_item.pixmap().toImage().pixelColor(0, 0)
        self.assertEqual(pixel.name(), "#0000ff")
        self.assertTrue(self.window.navigate_fullscreen(1))
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[3])
        self.assertTrue(self.window.leave_fullscreen(True))
        self.assertEqual(self.window.thumbnail_view.currentIndex().data(PATH_ROLE), self.paths[3])

    def test_cancelled_move_keeps_displayed_image(self):
        self.move([self.paths[1]], perform=False)
        self.assertTrue(os.path.exists(self.paths[1]))
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[1])

    def test_windowed_move_preserves_display_mode(self):
        self.window.fullscreen_viewer.toggle_display_mode()
        self.move([self.paths[1]])
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[2])
        self.assertEqual(self.window.fullscreen_viewer.display_mode, "windowed")
        self.assertFalse(self.window.fullscreen_viewer.isFullScreen())

    def test_returning_from_editors_preserves_windowed_mode(self):
        self.window.fullscreen_viewer.toggle_display_mode()
        with patch("ui.main_window.CropBoard") as crop:
            crop.return_value.exec.return_value = 0
            crop.return_value.saved_any = False
            self.window.open_crop_board(parent_override=self.window.fullscreen_viewer)
        self.assertEqual(self.window.fullscreen_viewer.display_mode, "windowed")
        with patch("ui.adjust_board.AdjustBoard") as adjust:
            adjust.return_value.exec.return_value = 0
            adjust.return_value.image_path = self.paths[1]
            self.window.open_adjust_board(parent_override=self.window.fullscreen_viewer)
        self.assertEqual(self.window.fullscreen_viewer.display_mode, "windowed")
        self.assertFalse(self.window.fullscreen_viewer.isFullScreen())

    def test_move_does_not_interrupt_navigation_to_another_image(self):
        self.window.navigate_fullscreen_to_path(self.paths[3])
        self.move([self.paths[1]])
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[3])

    def test_moving_last_image_uses_previous_without_wrapping(self):
        self.window.navigate_fullscreen_to_path(self.paths[3])
        self.move([self.paths[3]])
        self.assertEqual(self.window.fullscreen_viewer.current_image_path, self.paths[2])
        self.assertEqual(self.window.fullscreen_start_path, self.paths[2])

    def test_moving_all_images_closes_and_clears_fullscreen(self):
        self.move(self.paths)
        self.assertFalse(self.window.fullscreen_viewer.isVisible())
        self.assertIsNone(self.window.fullscreen_viewer.current_image_path)
        self.assertIsNone(self.window.current_image_path)
        self.assertTrue(self.window.fullscreen_viewer.viewer.pixmap_item.pixmap().isNull())
