import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from ui.about_dialog import AboutDialog, SHORTCUTS, install_about_shortcut
from ui.adjust_board import AdjustBoard
from ui.crop_board import CropBoard
from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog
from utils import file_ops
from utils.app_info import RELEASE_TAG, bundled_file


class AboutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.patch_config.start()
        file_ops.set_startup_behavior("empty")
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            if isinstance(window, MainWindow):
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
            window.close()
        self.app.processEvents()
        self.patch_config.stop()
        self.temp.cleanup()

    def keep(self, window):
        self.windows.append(window)
        return window

    def test_offline_license_changelog_and_all_shortcut_sections(self):
        dialog = self.keep(AboutDialog())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", dialog.license_browser.toPlainText())
        self.assertIn(RELEASE_TAG, dialog.changelog_browser.toPlainText())
        self.assertIn("v1.0.0-20260918", dialog.changelog_browser.toPlainText())
        self.assertTrue(bundled_file("A5ImageViewer.ico").is_file())
        self.assertEqual(dialog.tabs.count(), 3)
        for section in SHORTCUTS:
            dialog.section_combo.setCurrentText(section)
            self.assertIn(section, dialog.shortcut_browser.toPlainText())
            self.assertIn("F1", dialog.shortcut_browser.toPlainText())

    def test_f1_opens_contextual_help_from_each_window(self):
        path = os.path.join(self.temp.name, "image.png")
        Image.new("RGB", (64, 48), "red").save(path)
        main = self.keep(MainWindow())
        for window, section in (
            (main, "Browser"),
            (main.fullscreen_viewer, "Image viewer (fullscreen / windowed)"),
            (self.keep(CropBoard(path)), "Crop Board"),
            (self.keep(AdjustBoard(path)), "Adjust Colors & Size"),
            (self.keep(SettingsDialog(main)), "Settings and dialogs"),
        ):
            window.show()
            window.activateWindow()
            window.setFocus()
            self.app.processEvents()
            with patch("ui.about_dialog.show_about") as about:
                QTest.keyClick(window, Qt.Key.Key_F1)
                about.assert_called_once_with(window, section)
            window.hide()

    def test_disable_f1_updates_existing_and_new_windows_and_persists(self):
        owner = self.keep(QWidget())
        shortcut = install_about_shortcut(owner, "Browser")
        dialog = self.keep(AboutDialog(owner))
        self.assertTrue(shortcut.isEnabled())
        dialog.disable_f1_check.setChecked(True)
        self.assertFalse(shortcut.isEnabled())
        self.assertTrue(file_ops.get_disable_f1_shortcut())
        settings = self.keep(SettingsDialog())
        self.assertFalse(settings.findChild(QShortcut, "aboutShortcut").isEnabled())
        reopened = self.keep(AboutDialog())
        self.assertTrue(reopened.disable_f1_check.isChecked())
        reopened.disable_f1_check.setChecked(False)
        self.assertTrue(shortcut.isEnabled())
        self.assertTrue(settings.findChild(QShortcut, "aboutShortcut").isEnabled())

    def test_settings_button_works_with_f1_disabled_without_saving_pending_settings(self):
        file_ops.set_disable_f1_shortcut(True)
        settings = self.keep(SettingsDialog())
        original = file_ops.load_config()
        settings.image_limit_spin.setValue(4096)
        settings.show()
        settings.activateWindow()
        self.app.processEvents()
        with patch("ui.about_dialog.show_about") as about:
            QTest.keyClick(settings, Qt.Key.Key_F1)
            about.assert_not_called()
        with patch("ui.settings_dialog.show_about") as about:
            settings.about_button.click()
            about.assert_called_once_with(settings, "Settings and dialogs")
        self.assertEqual(file_ops.load_config(), original)

    def test_escape_closes_about_without_editing_preferences(self):
        original = file_ops.load_config()
        dialog = self.keep(AboutDialog())
        dialog.show()
        self.app.processEvents()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(file_ops.load_config(), original)

    def test_invalid_f1_preference_defaults_to_enabled(self):
        file_ops.save_config({"disable_f1_shortcut": "true"})
        self.assertFalse(file_ops.get_disable_f1_shortcut())
