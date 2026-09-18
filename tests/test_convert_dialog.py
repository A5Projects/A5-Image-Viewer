import os
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from ui.convert_dialog import ConvertDialog, ConvertWorker
from utils import file_ops


class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def make_image(self, name, color="red"):
        path = os.path.join(self.temp.name, name)
        Image.new("RGB", (8, 6), color).save(path)
        return path

    def test_uppercase_extension_in_place_rotation_does_not_delete_result(self):
        path = self.make_image("photo.PNG")
        worker = ConvertWorker([path], None, "", None, "right", 90, False, True)
        worker.run()
        with Image.open(os.path.join(self.temp.name, "photo.png")) as result:
            self.assertEqual(result.size, (6, 8))

    def test_distinct_source_is_deleted_after_conversion(self):
        path = self.make_image("photo.bmp")
        worker = ConvertWorker([path], None, "_result", "PNG", None, 90, False, True)
        worker.run()
        self.assertFalse(os.path.exists(path))
        with Image.open(os.path.join(self.temp.name, "photo_result.png")) as result:
            self.assertEqual(result.getpixel((0, 0)), (255, 0, 0))

    def test_colliding_outputs_are_rejected_before_any_file_changes(self):
        first = self.make_image("photo.png")
        second = self.make_image("photo.bmp", "blue")
        worker = ConvertWorker([first, second], None, "_result", "PNG", None, 90, False, True)
        errors = []
        worker.error.connect(lambda path, message: errors.append(message))
        worker.run()
        self.assertTrue(errors)
        self.assertTrue(os.path.exists(first))
        self.assertTrue(os.path.exists(second))
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "photo_result.png")))

    def test_output_cannot_overwrite_another_selected_source(self):
        first = self.make_image("photo.png")
        second = self.make_image("photo_result.png", "blue")
        worker = ConvertWorker([first, second], None, "_result", "PNG", None, 90, False, True)
        worker.run()
        with Image.open(second) as result:
            self.assertEqual(result.getpixel((0, 0)), (0, 0, 255))
        self.assertTrue(os.path.exists(first))

    def test_dialog_reports_collisions_without_starting_worker(self):
        dialog = ConvertDialog([self.make_image("photo.png"), self.make_image("photo.bmp")])
        self.addCleanup(dialog.close)
        dialog.format_combo.setCurrentText("PNG")
        with patch("ui.convert_dialog.QMessageBox.warning") as warning:
            dialog.start_conversion()
        warning.assert_called_once()
        self.assertIsNone(dialog.worker)
        self.assertTrue(dialog.convert_btn.isEnabled())

    def test_escape_and_close_are_blocked_until_worker_finishes(self):
        release = threading.Event()
        entered = threading.Event()
        dialog = ConvertDialog([])
        worker = ConvertWorker([], None, "", "PNG", None, 90, False, False)

        def held_run():
            entered.set()
            release.wait(5)

        with patch.object(worker, "run", held_run):
            dialog.worker = worker
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                dialog.show()
                self.app.processEvents()
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
                self.assertTrue(dialog.isVisible())
                dialog.close()
                self.assertTrue(dialog.isVisible())
                self.assertTrue(worker.isRunning())
            finally:
                release.set()
                worker.wait()
                dialog.close()

    def test_completion_joins_worker_and_accepts_dialog(self):
        dialog = ConvertDialog([])
        worker = ConvertWorker([], None, "", "PNG", None, 90, False, False)
        dialog.worker = worker
        worker.start()
        with patch("ui.convert_dialog.QMessageBox.information"):
            dialog.on_finished(0, 0)
        self.assertFalse(worker.isRunning())
        self.assertIsNone(dialog.worker)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
