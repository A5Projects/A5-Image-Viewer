import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow

from ui.main_window import MainWindow


class PromptHarness(MainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        self.image_modified = True
        self.modified_pixmap = object()
        self.current_image_path = "image.png"
        self._session_auto_save_edits = False
        self.save_calls = 0

    def save_modified_to_original(self):
        self.save_calls += 1
        self.image_modified = False
        self.modified_pixmap = None
        return True


class SavePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_enter_uses_save_default(self):
        window = PromptHarness()
        observed = {}

        def press_enter():
            message_box = QApplication.activeModalWidget()
            observed["default"] = message_box.defaultButton().text()
            QTest.keyClick(message_box, Qt.Key.Key_Return)

        QTimer.singleShot(0, press_enter)
        self.assertTrue(window.prompt_save_changes())
        self.assertEqual(observed["default"], "&Save")
        self.assertEqual(window.save_calls, 1)
        window.close()

    def test_plain_d_discards_and_can_enable_session_auto_save(self):
        window = PromptHarness()

        def discard():
            message_box = QApplication.activeModalWidget()
            message_box.checkBox().setChecked(True)
            QTest.keyClick(message_box, Qt.Key.Key_D)

        QTimer.singleShot(0, discard)
        self.assertTrue(window.prompt_save_changes())
        self.assertFalse(window.image_modified)
        self.assertTrue(window._session_auto_save_edits)
        self.assertEqual(window.save_calls, 0)

        window.image_modified = True
        window.modified_pixmap = object()
        self.assertTrue(window.prompt_save_changes())
        self.assertEqual(window.save_calls, 1)
        window.close()

if __name__ == "__main__":
    unittest.main()
