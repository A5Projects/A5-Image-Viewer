import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImageReader, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from ui.adjust_board import AdjustBoard
from ui.crop_board import CropBoard, _read_prefetch_image
from ui.fullscreen_viewer import FullscreenImageViewer
from ui.image_viewer import ImageViewer
from ui.settings_dialog import SettingsDialog
from utils import file_ops, image_loading
from utils.image_loading import ImageLoadError, MIB, read_full_image, read_pil_image


class ImageLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.qt_limit = QImageReader.allocationLimit()
        self.pil_limit = Image.MAX_IMAGE_PIXELS
        self.addCleanup(QImageReader.setAllocationLimit, self.qt_limit)
        self.addCleanup(setattr, Image, "MAX_IMAGE_PIXELS", self.pil_limit)
        self.path = os.path.join(self.temp.name, "sample.jpg")
        Image.new("RGB", (1200, 1000), "blue").save(self.path)

    def small_limit(self, limit):
        # Exercise actual decoder limits without allocating hundreds of MiB.
        return patch.object(image_loading, "get_image_settings", return_value={"max_decoded_image_mb": limit})

    def test_defaults_and_invalid_values(self):
        expected = {"max_decoded_image_mb": 1024, "smooth_downscaling": True}
        self.assertEqual(file_ops.get_image_settings(), expected)
        for value in (None, "4096", True, -1, 0, 63, 65537):
            file_ops.save_config({"max_decoded_image_mb": value, "smooth_downscaling": "false"})
            self.assertEqual(file_ops.get_image_settings(), expected)

    def test_settings_persist_and_apply_to_both_decoders(self):
        file_ops.save_config({"unrelated": "keep"})
        dialog = SettingsDialog()
        dialog.image_limit_spin.setValue(4096)
        dialog.smooth_check.setChecked(False)
        changes = []
        dialog.image_settings_changed.connect(changes.append)
        dialog.accept()
        self.assertEqual(changes, [{"max_decoded_image_mb": 4096, "smooth_downscaling": False}])
        self.assertEqual(QImageReader.allocationLimit(), 4096)
        self.assertEqual(Image.MAX_IMAGE_PIXELS, 4096 * MIB // 4)
        self.assertEqual(file_ops.load_config()["unrelated"], "keep")
        reopened = SettingsDialog()
        self.assertEqual(reopened.image_limit_spin.value(), 4096)
        self.assertFalse(reopened.smooth_check.isChecked())
        reopened.reject()

    def test_reject_settings_does_not_change_policy(self):
        dialog = SettingsDialog()
        dialog.image_limit_spin.setValue(2048)
        dialog.smooth_check.setChecked(False)
        dialog.reject()
        self.assertEqual(file_ops.get_image_settings()["max_decoded_image_mb"], 1024)
        self.assertTrue(file_ops.get_image_settings()["smooth_downscaling"])

    def test_size_limit_reports_required_memory_before_decoding(self):
        with patch.object(image_loading, "QImageReader") as factory:
            factory.return_value.size.return_value = QSize(22399, 7000)
            with self.small_limit(256), self.assertRaisesRegex(ImageLoadError, "599 MiB.*256 MiB") as caught:
                read_full_image(self.path)
            self.assertIn("Maximum decoded image size", str(caught.exception))
            factory.return_value.read.assert_not_called()

    def test_raising_limit_allows_full_resolution_in_qt_and_adjust(self):
        for loader in (read_full_image, AdjustBoard.read_image):
            with self.small_limit(4), self.assertRaises(ImageLoadError):
                loader(self.path)
            with self.small_limit(8):
                result = loader(self.path)
            if isinstance(result, Image.Image):
                self.assertEqual(result.size, (1200, 1000))
                result.close()
            else:
                self.assertEqual(result.size(), QSize(1200, 1000))

    def test_limit_failure_releases_windows_file_handle(self):
        with self.small_limit(4), self.assertRaises(ImageLoadError) as caught:
            read_full_image(self.path)
        os.rename(self.path, self.path + ".renamed")
        self.assertIsNotNone(caught.exception)

    def test_corrupt_file_reports_decode_error_not_limit(self):
        with open(self.path, "wb") as file:
            file.write(b"not a JPEG")
        for loader in (read_full_image, read_pil_image):
            with self.assertRaises(ImageLoadError) as caught:
                loader(self.path)
            self.assertIn("Unable to open image", str(caught.exception))
            self.assertNotIn("Increase Maximum", str(caught.exception))

    def test_failed_viewer_load_clears_old_image_and_recovers(self):
        view = ImageViewer()
        self.addCleanup(view.close)
        self.assertTrue(view.load_image(self.path))
        with self.small_limit(4):
            self.assertFalse(view.load_image(self.path))
        self.assertTrue(view.pixmap_item.pixmap().isNull())
        self.assertIn("Maximum decoded image size", view.error_label.text())
        self.assertFalse(view.error_label.isHidden())
        self.assertTrue(view.load_image(self.path))
        self.assertFalse(view.pixmap_item.pixmap().isNull())
        self.assertTrue(view.error_label.isHidden())
        self.assertEqual(view.last_error, "")

    def test_crop_failure_preserves_previous_image_and_selection(self):
        board = CropBoard(self.path)
        self.addCleanup(board.reject)
        board.select_all()
        previous = board.current_pixmap.cacheKey()
        selection = board.view.selection_rect_item.rect()
        with self.small_limit(4), patch("ui.crop_board.QMessageBox.warning") as warning:
            self.assertFalse(board.load_image(self.path))
        warning.assert_called_once()
        self.assertEqual(board.current_pixmap.cacheKey(), previous)
        self.assertEqual(board.view.selection_rect_item.rect(), selection)
        self.assertEqual(board.image_path, self.path)

    def test_prefetch_skips_large_header_even_with_large_cache(self):
        with patch("ui.crop_board.QImageReader") as factory:
            factory.return_value.size.return_value = QSize(10000, 7000)
            self.assertIsNone(_read_prefetch_image(self.path, 1024 * MIB))
            factory.return_value.read.assert_not_called()

    def test_prefetch_small_images_still_load_and_respect_smaller_budget(self):
        image_loading.apply_image_loading_settings()
        self.assertIsNotNone(_read_prefetch_image(self.path, 1024 * MIB))
        self.assertIsNone(_read_prefetch_image(self.path, 1 * MIB))

    def test_cpu_smoothing_tracks_zoom_and_can_be_disabled(self):
        view = FullscreenImageViewer()
        self.addCleanup(view.close)
        view.resize(400, 300)
        view.set_pixmap(QPixmap(1200, 1000))
        view.show()

        def rendered_mode():
            self.app.processEvents()
            view.viewport().grab()
            return view.pixmap_item.transformationMode()

        self.assertIs(type(view.viewport()), QWidget)
        self.assertEqual(rendered_mode(), Qt.TransformationMode.SmoothTransformation)
        view.actual_size()
        self.assertEqual(rendered_mode(), Qt.TransformationMode.FastTransformation)
        view.zoom_200()
        self.assertEqual(rendered_mode(), Qt.TransformationMode.FastTransformation)
        view.fit_to_window()
        self.assertEqual(rendered_mode(), Qt.TransformationMode.SmoothTransformation)
        view.apply_image_settings({"smooth_downscaling": False})
        self.assertEqual(rendered_mode(), Qt.TransformationMode.FastTransformation)
        view.apply_image_settings({"smooth_downscaling": True})
        view.actual_size()
        view.zoom_out()
        self.assertEqual(rendered_mode(), Qt.TransformationMode.SmoothTransformation)
