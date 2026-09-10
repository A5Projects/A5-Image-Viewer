import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from ui.dialogs import RenameDialog


class RenameDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()
