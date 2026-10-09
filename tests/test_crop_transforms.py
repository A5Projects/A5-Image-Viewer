import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox, QGraphicsRectItem

from ui.crop_board import CropBoard
from ui.main_window import MainWindow
from utils import file_ops


class CropTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        CropBoard._session_navigation_choice = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp_dir.name, "config.json"))
        self.config_patch.start()
        file_ops.set_startup_behavior("empty")
        self.image_path = os.path.join(self.temp_dir.name, "image.png")
        Image.new("RGB", (6, 4), "red").save(self.image_path)
        self.board = CropBoard(self.image_path)
        self.board.overwrite_check.setChecked(False)

    def tearDown(self):
        self.board.reject()
        CropBoard._session_navigation_choice = None
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def test_rotate_and_flip_are_undoable_unsaved_changes(self):
        self.board.rotate_left()
        self.assertEqual(
            (self.board.current_pixmap.width(), self.board.current_pixmap.height()),
            (4, 6),
        )
        self.assertTrue(self.board.has_unsaved_changes())
        self.assertEqual(len(self.board.history), 1)

        self.board.flip_horizontal()
        self.assertEqual(len(self.board.history), 2)
        self.board.undo()
        self.board.undo()
        self.assertEqual(
            (self.board.current_pixmap.width(), self.board.current_pixmap.height()),
            (6, 4),
        )
        self.assertFalse(self.board.has_unsaved_changes())

    def test_ctrl_a_selects_full_current_image_and_replaces_selection(self):
        self.board.show()
        self.board.activateWindow()
        self.board.view.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.board.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        selection = self.board.view.selection_rect_item
        self.assertIsNotNone(selection)
        self.assertEqual(selection.rect(), QRectF(0, 0, 6, 4))
        self.assertTrue(selection.isSelected())
        self.assertTrue(selection.handles)
        self.assertFalse(self.board.has_unsaved_changes())
        selection.setRect(QRectF(1, 1, 2, 2))
        QTest.keyClick(self.board.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.board.view.selection_rect_item.rect(), QRectF(0, 0, 6, 4))
        self.board.rotate_right()
        QTest.keyClick(self.board.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.board.view.selection_rect_item.rect(), QRectF(0, 0, 4, 6))

    def test_transformed_result_uses_existing_save_path(self):
        self.board.rotate_right()
        self.assertTrue(self.board.save_current_file())
        with Image.open(self.image_path) as saved:
            self.assertEqual(saved.size, (4, 6))
        self.assertFalse(self.board.has_unsaved_changes())

    def test_compact_toolbar_contains_transform_controls(self):
        self.assertEqual(
            set(self.board.tool_buttons),
            {
                "previous", "next", "crop", "undo", "reset",
                "rotate_left", "rotate", "flip_h", "flip_v",
            },
        )
        for button in self.board.tool_buttons.values():
            self.assertEqual((button.width(), button.height()), (34, 34))
        self.assertEqual(
            list(self.board.tool_buttons),
            [
                "previous", "next", "crop", "undo", "rotate_left",
                "rotate", "flip_h", "flip_v", "reset",
            ],
        )

    def test_toolbar_labels_are_compact_and_buttons_show_press_feedback(self):
        self.assertEqual(self.board.auto_name_check.text(), "Auto")
        self.assertEqual(self.board.overwrite_check.text(), "Ask")

        button = self.board.crop_file_btn
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        self.assertTrue(button.property("cropPressFeedback"))
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        self.assertTrue(button.property("cropPressFeedback"))
        deadline = time.monotonic() + 2.0
        while button.property("cropPressFeedback") and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(button.property("cropPressFeedback"))

        symbol_button = self.board.tool_buttons["crop"]
        QTest.mousePress(symbol_button, Qt.MouseButton.LeftButton)
        self.assertTrue(symbol_button.property("cropPressFeedback"))
        QTest.mouseRelease(symbol_button, Qt.MouseButton.LeftButton)

    def test_navigation_prompt_has_mnemonics_and_plain_d_remembers_discard(self):
        self.board.rotate_right()
        observed = {}

        def discard():
            msg = QApplication.activeModalWidget()
            self.assertIsInstance(msg, QMessageBox)
            observed["buttons"] = [button.text() for button in msg.buttons()]
            observed["default"] = msg.defaultButton().text()
            observed["checkbox"] = msg.checkBox().text()
            msg.checkBox().setChecked(True)
            QTest.keyClick(msg, Qt.Key.Key_D)

        QTimer.singleShot(0, discard)
        self.assertTrue(self.board.confirm_navigation())
        self.assertCountEqual(observed["buttons"], ["&Save", "&Discard", "&Cancel"])
        self.assertEqual(observed["default"], "&Save")
        self.assertEqual(observed["checkbox"], "Don't ask again this session")
        self.assertEqual(CropBoard._session_navigation_choice, "discard")

        self.board.rotate_left()
        self.assertTrue(self.board.confirm_navigation())

    def test_navigation_prompt_plain_s_remembers_save_and_cancel_does_not(self):
        self.board.rotate_right()

        def save():
            msg = QApplication.activeModalWidget()
            msg.checkBox().setChecked(True)
            QTest.keyClick(msg, Qt.Key.Key_S)

        with patch.object(self.board, "save_current_file", return_value=True) as save_file:
            QTimer.singleShot(0, save)
            self.assertTrue(self.board.confirm_navigation())
            self.assertEqual(CropBoard._session_navigation_choice, "save")
            self.assertTrue(self.board.confirm_navigation())
            self.assertEqual(save_file.call_count, 2)

        CropBoard._session_navigation_choice = None

        def cancel():
            msg = QApplication.activeModalWidget()
            msg.checkBox().setChecked(True)
            QTest.keyClick(msg, Qt.Key.Key_C)

        QTimer.singleShot(0, cancel)
        self.assertFalse(self.board.confirm_navigation())
        self.assertIsNone(CropBoard._session_navigation_choice)

    def test_crop_shortcut_transforms_crop_state_not_main_preview(self):
        main_window = MainWindow()
        board = None
        try:
            main_window.current_image_path = self.image_path
            main_window.current_item_kind = "image"
            board = CropBoard(self.image_path, main_window)
            board.show()
            board.activateWindow()
            board.setFocus()
            QTest.keyClick(board, Qt.Key.Key_L)
            QTest.qWait(20)
            self.assertEqual(
                (board.current_pixmap.width(), board.current_pixmap.height()),
                (4, 6),
            )
            self.assertFalse(main_window.image_modified)
        finally:
            if board is not None:
                board.reject()
            main_window.thumbnail_view.shutdown()
            main_window.crop_prefetch_service.shutdown()
            main_window.close()

    def test_drawn_crop_selection_immediately_shows_resize_handles(self):
        self.board.resize(800, 600)
        self.board.show()
        QApplication.processEvents()

        viewport = self.board.view.viewport()
        start = self.board.view.mapFromScene(QPointF(0.5, 0.5))
        end = self.board.view.mapFromScene(QPointF(4.5, 3.0))
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)

        selection = self.board.view.selection_rect_item
        self.assertIsNotNone(selection)
        self.assertTrue(selection.isSelected())
        self.assertEqual(len(selection.handles), 8)
        self.assertTrue(selection.rect().isValid())

    def test_crop_to_file_uses_unique_suffix_and_optional_auto_naming(self):
        first_path = os.path.join(self.temp_dir.name, "image_crop.png")
        Image.new("RGB", (1, 1), "blue").save(first_path)
        self.assertEqual(
            self.board.unique_cropped_path(),
            os.path.join(self.temp_dir.name, "image_crop2.png"),
        )

        self.board.view.selection_rect_item = QGraphicsRectItem(
            0, 0, 3, 2
        )
        self.board.auto_name_check.setChecked(True)
        self.assertTrue(self.board.auto_name_check.isChecked())
        self.assertTrue(self.board.crop_to_file())
        self.assertTrue(
            os.path.isfile(os.path.join(self.temp_dir.name, "image_crop2.png"))
        )

    def test_manual_crop_numbers_in_chosen_folder_and_remembers_it_on_reopen(self):
        output = os.path.join(self.temp_dir.name, "crops")
        os.mkdir(output)
        existing = os.path.join(output, "image_crop.png")
        Image.new("RGB", (1, 1), "blue").save(existing)
        os.mkdir(os.path.join(output, "image_crop2.png"))
        self.board.select_all()
        self.board.view.selection_rect_item.setRect(QRectF(1, 1, 3, 2))
        saved = []
        self.board.image_saved.connect(saved.append)
        with patch("ui.crop_board.QFileDialog.getExistingDirectory", return_value=output) as choose:
            self.assertTrue(self.board.crop_to_file())
        self.assertEqual(choose.call_args.args[2], self.temp_dir.name)
        result = os.path.join(output, "image_crop3.png")
        self.assertEqual(saved, [result])
        with Image.open(result) as image:
            self.assertEqual(image.size, (3, 2))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        with Image.open(existing) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(file_ops.load_config()["crop_output_folder"], output)
        self.assertFalse(self.board.has_unsaved_changes())

        self.board.reject()
        self.board = CropBoard(self.image_path)
        self.board.select_all()
        with patch("ui.crop_board.QFileDialog.getExistingDirectory", return_value=output) as choose:
            self.assertTrue(self.board.crop_to_file())
        self.assertEqual(choose.call_args.args[2], output)
        self.assertTrue(os.path.isfile(os.path.join(output, "image_crop4.png")))

    def test_auto_crop_follows_current_image_without_changing_manual_destination(self):
        manual = os.path.join(self.temp_dir.name, "manual")
        other = os.path.join(self.temp_dir.name, "other")
        os.mkdir(manual)
        os.mkdir(other)
        file_ops.set_crop_output_folder(manual)
        self.board.auto_name_check.setChecked(True)
        self.assertIn("current image's folder", self.board.crop_file_btn.toolTip())
        self.board.select_all()
        other_path = os.path.join(other, "second.png")
        Image.new("RGB", (9, 7), "green").save(other_path)
        with patch("ui.crop_board.QFileDialog.getExistingDirectory") as choose:
            self.assertTrue(self.board.crop_to_file())
            self.board.load_image(other_path)
            self.board.select_all()
            self.assertTrue(self.board.crop_to_file())
            choose.assert_not_called()
        self.assertTrue(os.path.isfile(os.path.join(self.temp_dir.name, "image_crop.png")))
        self.assertTrue(os.path.isfile(os.path.join(other, "second_crop.png")))
        self.assertEqual(os.listdir(manual), [])
        self.assertEqual(file_ops.get_crop_output_folder(), manual)
        self.board.auto_name_check.setChecked(False)
        self.assertIn("last manual destination", self.board.crop_file_btn.toolTip())

    def test_cancelled_or_failed_manual_crop_preserves_destination_and_selection(self):
        file_ops.set_crop_output_folder(self.temp_dir.name)
        self.board.select_all()
        selection = self.board.view.selection_rect_item.rect()
        saved = []
        self.board.image_saved.connect(saved.append)
        with patch("ui.crop_board.QFileDialog.getExistingDirectory", return_value=""):
            self.assertFalse(self.board.crop_to_file())
        missing = os.path.join(self.temp_dir.name, "missing")
        with (patch("ui.crop_board.QFileDialog.getExistingDirectory", return_value=missing),
              patch("ui.crop_board.QMessageBox.warning") as warning):
            self.assertFalse(self.board.crop_to_file())
            warning.assert_called_once()
        self.assertEqual(file_ops.get_crop_output_folder(), self.temp_dir.name)
        self.assertEqual(self.board.view.selection_rect_item.rect(), selection)
        self.assertEqual(saved, [])
        self.assertFalse(self.board.saved_any)
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir.name, "image_crop.png")))

    def test_invalid_or_unavailable_manual_folder_falls_back_to_current_image_folder(self):
        self.board.select_all()
        for value in (None, 123, [], "", self.image_path, os.path.join(self.temp_dir.name, "missing")):
            with self.subTest(value=value):
                file_ops.save_config({"crop_output_folder": value})
                with patch("ui.crop_board.QFileDialog.getExistingDirectory", return_value="") as choose:
                    self.assertFalse(self.board.crop_to_file())
                self.assertEqual(choose.call_args.args[2], self.temp_dir.name)


if __name__ == "__main__":
    unittest.main()
