import os
import unittest
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtTest import QTest

from ui.dialogs import RenameDialog
from ui.main_window import MainWindow


class RenameDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def finish_attempt(self, dialog):
        deadline = time.monotonic() + 3
        while dialog.worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        if dialog.worker is not None:
            dialog.reject()
            dialog.worker.wait(2000)
            self.app.processEvents()
            self.fail("Rename did not finish in time")

    def test_splits_basename_and_extension_and_recombines_edits(self):
        dialog = RenameDialog("photo.final.webp")
        self.assertEqual(dialog.name_edit.text(), "photo.final")
        self.assertEqual(dialog.extension_edit.text(), "webp")

        dialog.name_edit.setText("renamed")
        dialog.extension_edit.setText("png")
        dialog.accept_rename()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.new_filename, "renamed.png")

    def test_extension_accepts_an_optional_leading_period(self):
        dialog = RenameDialog("photo.jpg")
        dialog.extension_edit.setText(".webp")
        dialog.accept_rename()
        self.assertEqual(dialog.new_filename, "photo.webp")

    def test_rejects_windows_invalid_names(self):
        dialog = RenameDialog("photo.jpg")
        dialog.name_edit.setText("bad/name")
        with patch.object(QMessageBox, "warning") as warning:
            dialog.accept_rename()
        warning.assert_called_once()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_collision_keeps_attempted_name_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source.txt")
            existing = os.path.join(folder, "existing.txt")
            for path, content in ((source, "source"), (existing, "keep")):
                with open(path, "w") as file:
                    file.write(content)
            updates = []
            owner = SimpleNamespace(
                current_image_path=source,
                selected_image_paths=lambda: [],
                row_for_path=lambda path: 0,
                update_renamed_thumbnail_item=lambda *args: updates.append(args),
                refocus_fullscreen_if_visible=lambda: None,
                pause_file_access=lambda paths: False,
                resume_file_access=Mock(),
                thumbnail_view=SimpleNamespace(
                    interactive_background_paused=False, file_access_paused=False,
                    set_background_activity_paused=Mock(), set_file_access_paused=Mock(),
                ),
            )

            def run_dialog(dialog):
                dialog.show()
                dialog.name_edit.setText("existing")
                dialog.accept_rename()
                self.finish_attempt(dialog)
                self.assertTrue(dialog.isVisible())
                self.assertIn("already exists", dialog.error_label.text())
                self.assertEqual(dialog.name_edit.text(), "existing")
                self.assertEqual(dialog.extension_edit.text(), "txt")
                self.assertEqual(dialog.name_edit.selectedText(), "existing")
                self.assertTrue(os.path.exists(source))
                dialog.name_edit.setText("corrected")
                dialog.accept_rename()
                self.finish_attempt(dialog)
                return dialog.result()

            parent = QDialog()
            with patch.object(RenameDialog, "exec", run_dialog):
                MainWindow.rename_file(owner, parent_override=parent)
            target = os.path.join(folder, "corrected.txt")
            self.assertEqual(updates, [(0, source, target)])
            self.assertTrue(os.path.exists(target))
            self.assertFalse(os.path.exists(source))
            with open(existing) as file:
                self.assertEqual(file.read(), "keep")
            parent.close()

    def test_failed_rename_can_be_cancelled_without_accepting(self):
        dialog = RenameDialog("photo.png", rename_callback=lambda name: "Name is already in use.")
        dialog.name_edit.setText("attempted")
        dialog.accept_rename()
        self.finish_attempt(dialog)
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(dialog.new_filename, "photo.png")


if __name__ == "__main__":
    unittest.main()
