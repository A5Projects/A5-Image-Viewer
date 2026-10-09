import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImageReader
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from ui.dialogs import RenameDialog
from ui.main_window import MainWindow
from ui.thumbnail_view import _read_thumbnail_image
from utils import file_ops


class RenameReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), "Rename did not reach the expected state")

    @unittest.skipUnless(os.name == "nt", "Requires Windows file sharing semantics")
    def test_active_reader_retries_without_blocking_and_updates_viewer_paths(self):
        self.exercise_reader_conflict(cancel=False)

    @unittest.skipUnless(os.name == "nt", "Requires Windows file sharing semantics")
    def test_close_while_reader_is_locked_cancels_and_resumes_reading(self):
        self.exercise_reader_conflict(cancel=True)

    def exercise_reader_conflict(self, cancel):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            file_ops, "CONFIG_FILE", str(Path(folder) / "config.json")
        ):
            file_ops.set_startup_behavior("empty")
            source, target = Path(folder) / "old.png", Path(folder) / "new.png"
            Image.new("RGB", (640, 480), "red").save(source)
            opened, release = Event(), Event()
            sharing_errors, rename_threads, reader_paths = [], [], []
            real_rename = os.rename
            gui_thread = get_ident()

            def held_reader(path, size):
                reader_paths.append(path)
                if path != str(source) or opened.is_set():
                    return _read_thumbnail_image(path, size)
                reader = QImageReader(path)
                try:
                    if not reader.canRead():
                        raise RuntimeError("Test image could not be opened")
                    opened.set()
                    if not release.wait(8):
                        raise RuntimeError("Test reader was not released")
                    return reader.size(), reader.read()
                finally:
                    del reader

            def observed_rename(old, new):
                rename_threads.append(get_ident())
                try:
                    return real_rename(old, new)
                except OSError as error:
                    sharing_errors.append(getattr(error, "winerror", None))
                    raise

            window = MainWindow()
            dialogs, ticks = [], []
            try:
                with (
                    patch("ui.thumbnail_view._read_thumbnail_image", side_effect=held_reader),
                    patch("ui.batch_operations.os.rename", side_effect=observed_rename),
                ):
                    window.current_folder_path = folder
                    window.thumbnail_view.load_folder(folder, show_folders=False)
                    window.current_image_path = str(source)
                    window.current_item_kind = "image"
                    window.fullscreen_start_path = str(source)
                    window.fullscreen_viewer.set_current_image_path(str(source))
                    # Preserve the existing background pause (e.g. viewer open).
                    window.thumbnail_view.set_background_activity_paused(True)
                    self.assertTrue(opened.wait(3))

                    def run_dialog(dialog):
                        dialogs.append(dialog)
                        timer = QTimer(dialog)
                        timer.timeout.connect(lambda: ticks.append(1))
                        timer.start(10)
                        try:
                            dialog.show()
                            dialog.name_edit.setText("new")
                            dialog.accept_rename()
                            self.wait_until(lambda: sharing_errors and ticks)
                            self.assertEqual(sharing_errors[0], 32)
                            self.assertFalse(dialog.name_edit.isEnabled())
                            self.assertTrue(window.thumbnail_view.file_access_paused)
                            # Priority requests/model refreshes must not start
                            # another decoder while a rename is pending.
                            window.thumbnail_view.sync_worker_records()
                            window.thumbnail_view.prioritize_rows_around(0)
                            self.assertEqual(reader_paths, [str(source)])
                            if cancel:
                                dialog.close()
                            else:
                                release.set()
                            self.wait_until(lambda: dialog.worker is None)
                            return dialog.result()
                        finally:
                            timer.stop()

                    with patch.object(RenameDialog, "exec", run_dialog):
                        window.rename_file()
                    expected = source if cancel else target
                    self.assertTrue(expected.exists())
                    self.assertFalse((target if cancel else source).exists())
                    self.assertEqual(window.current_image_path, str(expected))
                    self.assertEqual(window.fullscreen_viewer.current_image_path, str(expected))
                    self.assertEqual(window.fullscreen_start_path, str(expected))
                    self.assertIsNotNone(window.thumbnail_view.item_for_path(str(expected)))
                    self.assertFalse(window.thumbnail_view.file_access_paused)
                    self.assertTrue(window.thumbnail_view.interactive_background_paused)
                    self.assertTrue(all(thread != gui_thread for thread in rename_threads))
            finally:
                release.set()
                for dialog in dialogs:
                    if dialog.worker is not None:
                        dialog.reject()
                        dialog.worker.wait(2000)
                        self.app.processEvents()
                    dialog.close()
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.transfer_coordinator.shutdown()
                window.close()
                self.app.processEvents()

    def test_completed_rename_wins_late_cancel_and_prevents_duplicate_submit(self):
        entered, release = Event(), Event()
        calls = []

        def callback(filename):
            calls.append(filename)
            entered.set()
            if not release.wait(3):
                return "Test callback timed out"
            return ""  # The rename has completed, despite a late Cancel.

        dialog = RenameDialog("old.png", rename_callback=callback)
        try:
            dialog.name_edit.setText("new")
            dialog.accept_rename()
            self.assertTrue(entered.wait(2))
            dialog.accept_rename()
            dialog.reject()
            release.set()
            self.wait_until(lambda: dialog.worker is None)
            self.assertEqual(calls, ["new.png"])
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.new_filename, "new.png")
        finally:
            release.set()
            if dialog.worker is not None:
                dialog.worker.wait(2000)
                self.app.processEvents()
            dialog.close()
