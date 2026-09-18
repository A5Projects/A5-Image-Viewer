import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QWidget

from ui.fullscreen_viewer import FullScreenViewer
from ui.settings_dialog import SettingsDialog
from utils import file_ops


class ViewerOwner(QWidget):
    def __init__(self):
        super().__init__()
        self.allow_close = True
        self.commits = []

    def leave_fullscreen(self, commit_current):
        self.commits.append(commit_current)
        return self.allow_close


class ViewerModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.path = os.path.join(self.temp.name, "sample.png")
        Image.new("RGB", (1800, 1200), "blue").save(self.path)
        self.owner = ViewerOwner()
        self.viewer = FullScreenViewer(self.owner)

    def tearDown(self):
        self.owner.allow_close = True
        self.viewer.close()
        self.app.processEvents()
        self.owner.close()
        self.config_patch.stop()
        self.temp.cleanup()

    def key(self, key):
        self.viewer.handle_key_press(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    def test_default_and_invalid_configuration_remain_fullscreen(self):
        self.assertEqual(file_ops.get_viewer_default_mode(), "fullscreen")
        file_ops.save_config({"viewer_default_mode": "invalid", "viewer_state": {"geometry": [0, 0, -1, "bad"], "mode": "invalid"}})
        self.assertIsNone(file_ops.get_viewer_state()["geometry"])
        self.assertEqual(file_ops.get_viewer_default_mode(), "fullscreen")
        self.viewer.load_image(self.path)
        self.assertTrue(self.viewer.isFullScreen())

    def test_settings_persist_opening_preference(self):
        dialog = SettingsDialog()
        dialog.viewer_mode_combo.setCurrentIndex(dialog.viewer_mode_combo.findData("last_used"))
        dialog.accept()
        self.assertEqual(file_ops.get_viewer_default_mode(), "last_used")

    def test_windowed_opens_maximized_and_navigation_keeps_mode(self):
        file_ops.set_viewer_default_mode("windowed")
        self.viewer.load_image(self.path)
        self.assertTrue(self.viewer.isMaximized())
        self.assertFalse(self.viewer.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertIn("sample.png", self.viewer.windowTitle())
        file_ops.set_viewer_default_mode("fullscreen")
        self.viewer.load_image(self.path)
        self.viewer.refocus()
        self.assertEqual(self.viewer.display_mode, "windowed")
        self.viewer.showMinimized()
        self.viewer.refocus()
        self.assertFalse(self.viewer.isMinimized())
        self.assertTrue(self.viewer.isMaximized())
        self.viewer.close()
        self.viewer.load_image(self.path)
        self.assertTrue(self.viewer.isFullScreen())

    def test_f11_preserves_pixels_selection_and_manual_zoom(self):
        self.viewer.load_image(self.path)
        self.viewer.select_all_pixels()
        self.viewer.viewer.zoom_200()
        selection = self.viewer.viewer.selection_rect()
        before = self.viewer.viewer.pixmap_item.pixmap().cacheKey()
        self.key(Qt.Key.Key_F11)
        self.app.processEvents()
        self.assertEqual(self.viewer.display_mode, "windowed")
        self.assertEqual(self.viewer.viewer.transform().m11(), 2)
        self.assertEqual(self.viewer.viewer.selection_rect(), selection)
        self.assertEqual(self.viewer.viewer.pixmap_item.pixmap().cacheKey(), before)
        self.key(Qt.Key.Key_F11)
        self.assertTrue(self.viewer.isFullScreen())
        self.assertEqual(self.viewer.viewer.transform().m11(), 2)

    def test_window_geometry_and_last_mode_survive_recreation(self):
        file_ops.set_viewer_default_mode("last_used")
        self.viewer.load_image(self.path)
        self.viewer.toggle_display_mode()
        self.viewer.showNormal()
        self.viewer.setGeometry(40, 50, 600, 400)
        self.app.processEvents()
        self.viewer.close()
        self.viewer = FullScreenViewer(self.owner)
        self.viewer.load_image(self.path)
        self.assertEqual(self.viewer.display_mode, "windowed")
        self.assertFalse(self.viewer.isMaximized())
        self.assertEqual(self.viewer.size().width(), 600)
        self.assertEqual(self.viewer.size().height(), 400)

    def test_offscreen_geometry_is_clamped_to_available_desktop(self):
        available = QRect(-1200, 0, 1200, 800)
        rect = self.viewer.bounded_geometry([20000, 20000, 4000, 3000], available)
        self.assertTrue(available.contains(rect))
        self.assertEqual(self.viewer.saved_screen("disconnected-screen"), self.owner.screen())

    def test_resize_refits_only_fit_mode(self):
        file_ops.set_viewer_default_mode("windowed")
        self.viewer.load_image(self.path)
        self.viewer.showNormal()
        self.viewer.resize(600, 400)
        self.app.processEvents()
        before = self.viewer.viewer.transform().m11()
        self.viewer.resize(900, 600)
        self.app.processEvents()
        self.assertGreater(self.viewer.viewer.transform().m11(), before)
        self.viewer.viewer.zoom_200()
        self.viewer.viewer.centerOn(750, 500)
        center = self.viewer.viewer.mapToScene(self.viewer.viewer.viewport().rect().center())
        self.viewer.resize(500, 400)
        self.app.processEvents()
        self.assertEqual(self.viewer.viewer.transform().m11(), 2)
        after = self.viewer.viewer.mapToScene(self.viewer.viewer.viewport().rect().center())
        self.assertAlmostEqual(center.x(), after.x(), delta=1)
        self.assertAlmostEqual(center.y(), after.y(), delta=1)

    def test_close_cancel_enter_and_escape_use_existing_selection_policy(self):
        self.viewer.load_image(self.path)
        self.owner.allow_close = False
        self.viewer.close()
        self.assertTrue(self.viewer.isVisible())
        self.assertEqual(self.owner.commits[-1], True)
        self.owner.allow_close = True
        self.key(Qt.Key.Key_Escape)
        self.assertFalse(self.viewer.isVisible())
        self.assertEqual(self.owner.commits[-1], False)
        self.viewer.load_image(self.path)
        self.key(Qt.Key.Key_Return)
        self.assertFalse(self.viewer.isVisible())
        self.assertEqual(self.owner.commits[-1], True)
