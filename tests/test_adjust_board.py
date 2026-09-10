import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.adjust_board import AdjustBoard
from utils import file_ops


class AdjustBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        AdjustBoard._session_navigation_choice = None
        self.original_config_file = file_ops.CONFIG_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        file_ops.CONFIG_FILE = os.path.join(self.temp_dir.name, "config.json")
        self.image_path = os.path.join(self.temp_dir.name, "image.png")
        self.second_path = os.path.join(self.temp_dir.name, "second.png")
        Image.new("RGBA", (8, 6), (40, 60, 80, 90)).save(self.image_path)
        Image.new("RGB", (12, 4), (120, 80, 40)).save(self.second_path)
        self.board = AdjustBoard(
            self.image_path,
            navigation_paths=[self.image_path, self.second_path],
        )

    def tearDown(self):
        self.board.close()
        AdjustBoard._session_navigation_choice = None
        file_ops.CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def test_numeric_inputs_and_sliders_stay_synchronized(self):
        self.board.value_inputs["Gamma"].setValue(1.55)
        self.assertEqual(self.board.sliders["Gamma"].value(), 155)

        self.board.sliders["Exposure"].setValue(-125)
        self.assertAlmostEqual(
            self.board.value_inputs["Exposure"].value(), -1.25
        )

        self.board.effect_checks["Invert"].setChecked(True)
        self.board.reset_adjustments()
        self.assertEqual(self.board.sliders["Gamma"].value(), 100)
        self.assertEqual(self.board.value_inputs["Gamma"].value(), 1.0)
        self.assertFalse(self.board.effect_checks["Invert"].isChecked())

    def test_channel_adjustments_preserve_alpha(self):
        self.board.sliders["Red"].setValue(100)
        source = Image.new("RGBA", (1, 1), (40, 60, 80, 90))

        result = self.board.apply_adjustments(source)

        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.getpixel((0, 0)), (80, 60, 80, 90))

    def test_grayscale_and_invert_are_applied_as_pixel_operations(self):
        self.board.effect_checks["Grayscale"].setChecked(True)
        self.board.effect_checks["Invert"].setChecked(True)
        source = Image.new("RGBA", (1, 1), (10, 20, 30, 77))

        result = self.board.apply_adjustments(source)
        red, green, blue, alpha = result.getpixel((0, 0))

        self.assertEqual(red, green)
        self.assertEqual(green, blue)
        self.assertEqual(alpha, 77)

    def test_auto_contrast_expands_tonal_range(self):
        self.board.effect_checks["Auto Contrast"].setChecked(True)
        source = Image.new("RGB", (2, 1))
        source.putdata([(50, 50, 50), (150, 150, 150)])

        result = self.board.apply_adjustments(source)

        self.assertEqual(
            [result.getpixel((0, 0)), result.getpixel((1, 0))],
            [(0, 0, 0), (255, 255, 255)],
        )

    def test_auto_contrast_ignores_sparse_black_and_white_outliers(self):
        self.board.effect_checks["Auto Contrast"].setChecked(True)
        source = Image.new("RGB", (100, 1))
        source.putdata(
            [(0, 0, 0)] +
            [(50, 50, 50)] * 49 +
            [(150, 150, 150)] * 49 +
            [(255, 255, 255)]
        )

        result = self.board.apply_adjustments(source)

        self.assertEqual(result.getpixel((1, 0)), (0, 0, 0))
        self.assertEqual(result.getpixel((50, 0)), (255, 255, 255))

    def test_resize_filter_choices_map_to_pillow_resampling(self):
        keys = {
            self.board.resample_combo.itemData(index)
            for index in range(self.board.resample_combo.count())
        }
        self.assertEqual(
            keys,
            {
                "auto", "lanczos", "lanczos_sharper", "bicubic",
                "bicubic_sharper", "bilinear", "hamming", "nearest", "box",
            },
        )
        for key in keys:
            self.assertIn(key, self.board.RESAMPLING_METHODS)

    def test_resize_preview_updates_for_free_and_fixed_aspect_ratios(self):
        self.board.check_aspect.setChecked(False)
        self.board.spin_width.setValue(8)
        self.board.spin_height.setValue(3)
        self.board.apply_preview_adjustments()
        self.assertEqual(self.board.preview_current_pil.size, (8, 3))
        self.assertEqual(
            (
                self.board.pixmap_item.pixmap().width(),
                self.board.pixmap_item.pixmap().height(),
            ),
            (8, 3),
        )

        self.board.check_aspect.setChecked(True)
        self.board.spin_width.setValue(4)
        self.board.apply_preview_adjustments()
        self.assertEqual(self.board.spin_height.value(), 3)
        self.assertEqual(self.board.preview_current_pil.size, (4, 3))

    def test_resize_preview_is_bounded_to_1200_pixels(self):
        self.board.check_aspect.setChecked(False)
        self.board.spin_width.setValue(2400)
        self.board.spin_height.setValue(600)

        self.board.apply_preview_adjustments()

        self.assertEqual(self.board.output_dimensions(), (2400, 600))
        self.assertEqual(self.board.preview_current_pil.size, (1200, 300))

    def test_navigation_stops_at_ends_and_adjustment_memory_controls_carryover(self):
        self.board.check_remember.setChecked(True)
        self.board.sliders["Brightness"].setValue(35)
        self.board.saved_signature = self.board.edit_signature()

        self.assertTrue(self.board.open_adjacent_image(1))
        self.assertEqual(self.board.image_path, self.second_path)
        self.assertEqual(self.board.sliders["Brightness"].value(), 35)
        self.assertFalse(self.board.open_adjacent_image(1))

        self.board.check_remember.setChecked(False)
        self.board.saved_signature = self.board.edit_signature()
        self.assertTrue(self.board.open_adjacent_image(-1))
        self.assertEqual(self.board.sliders["Brightness"].value(), 0)
        self.assertFalse(self.board.open_adjacent_image(-1))

    def test_remember_resize_recomputes_locked_pixel_dimension(self):
        self.board.check_remember_resize.setChecked(True)
        self.board.spin_width.setValue(4)
        self.assertEqual(self.board.output_dimensions(), (4, 3))
        self.board.saved_signature = self.board.edit_signature()

        self.assertTrue(self.board.open_adjacent_image(1))

        self.assertEqual(self.board.output_dimensions(), (4, 1))
        self.assertTrue(self.board.check_aspect.isChecked())
        self.assertEqual(self.board.resample_combo.currentData(), "auto")

    def test_resampling_choice_is_persisted_and_auto_selects_by_direction(self):
        self.assertEqual(self.board.resample_combo.currentData(), "auto")
        self.assertEqual(
            self.board.selected_resampling_method((100, 100), (50, 50)),
            Image.Resampling.LANCZOS,
        )
        self.assertEqual(
            self.board.selected_resampling_method((100, 100), (200, 200)),
            Image.Resampling.BICUBIC,
        )

        index = self.board.resample_combo.findData("bicubic_sharper")
        self.board.resample_combo.setCurrentIndex(index)
        self.assertEqual(file_ops.get_adjust_resampling(), "bicubic_sharper")

    def test_fit_fill_and_padding_geometry_render_expected_dimensions(self):
        source = Image.new("RGB", (4, 2), "red")

        self.board.geometry_combo.setCurrentIndex(
            self.board.geometry_combo.findData("fit")
        )
        self.assertEqual(self.board.render_resized_image(source, (4, 4)).size, (4, 2))

        self.board.geometry_combo.setCurrentIndex(
            self.board.geometry_combo.findData("fill")
        )
        self.assertEqual(self.board.render_resized_image(source, (4, 4)).size, (4, 4))

        self.board.geometry_combo.setCurrentIndex(
            self.board.geometry_combo.findData("pad")
        )
        self.board.padding_color.setNamedColor("#0000ff")
        padded = self.board.render_resized_image(source, (4, 4))
        self.assertEqual(padded.size, (4, 4))
        self.assertEqual(padded.getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(padded.getpixel((0, 2)), (255, 0, 0))

    def test_resize_resets_on_navigation_when_not_remembered(self):
        self.board.check_aspect.setChecked(False)
        self.board.spin_width.setValue(3)
        self.board.spin_height.setValue(2)
        self.board.saved_signature = self.board.edit_signature()

        self.assertTrue(self.board.open_adjacent_image(1))

        self.assertEqual(self.board.resize_mode_combo.currentData(), "pixels")
        self.assertEqual(self.board.output_dimensions(), (12, 4))
        self.assertTrue(self.board.check_aspect.isChecked())

    def test_remember_resize_keeps_percent_and_unlocked_pixel_values(self):
        self.board.check_remember_resize.setChecked(True)
        self.board.resize_mode_combo.setCurrentIndex(
            self.board.resize_mode_combo.findData("percent")
        )
        self.board.check_aspect.setChecked(False)
        self.board.spin_width.setValue(50)
        self.board.spin_height.setValue(25)
        self.board.saved_signature = self.board.edit_signature()

        self.assertTrue(self.board.open_adjacent_image(1))
        self.assertEqual(self.board.resize_mode_combo.currentData(), "percent")
        self.assertEqual((self.board.spin_width.value(), self.board.spin_height.value()), (50, 25))
        self.assertEqual(self.board.output_dimensions(), (6, 1))

        self.board.resize_mode_combo.setCurrentIndex(
            self.board.resize_mode_combo.findData("pixels")
        )
        self.board.check_aspect.setChecked(False)
        self.board.spin_width.setValue(7)
        self.board.spin_height.setValue(3)
        self.board.saved_signature = self.board.edit_signature()

        self.assertTrue(self.board.open_adjacent_image(-1))
        self.assertEqual(self.board.output_dimensions(), (7, 3))
        self.assertFalse(self.board.check_aspect.isChecked())

    def test_auto_named_copies_are_unique_persisted_and_mark_state_saved(self):
        self.board.sliders["Contrast"].setValue(20)
        self.board.check_auto_name.setChecked(True)

        self.assertTrue(self.board.apply_and_save())
        first_copy = os.path.join(self.temp_dir.name, "image_adj.png")
        self.assertTrue(os.path.isfile(first_copy))
        self.assertEqual(self.board.image_path, self.image_path)
        self.assertFalse(self.board.has_unsaved_changes())
        self.assertTrue(file_ops.get_adjust_auto_name_copies())

        self.board.sliders["Contrast"].setValue(30)
        self.assertTrue(self.board.apply_and_save())
        self.assertTrue(os.path.isfile(os.path.join(self.temp_dir.name, "image_adj2.png")))

    def test_save_to_file_starts_in_source_folder_with_adj_name(self):
        output_path = os.path.join(self.temp_dir.name, "manual.png")
        observed = {}

        def choose_file(parent, title, initial_path, filters):
            observed["title"] = title
            observed["initial_path"] = initial_path
            return output_path, filters

        with patch(
            "ui.adjust_board.QFileDialog.getSaveFileName",
            side_effect=choose_file,
        ):
            self.assertTrue(self.board.save_to_file())

        self.assertEqual(observed["title"], "Save Adjusted Image")
        self.assertEqual(
            observed["initial_path"],
            os.path.join(self.temp_dir.name, "image_adj.png"),
        )
        self.assertTrue(os.path.isfile(output_path))
        self.assertEqual(self.board.image_path, self.image_path)

    def test_normal_save_dialog_offers_overwrite_save_as_and_adj_copy(self):
        self.board.sliders["Brightness"].setValue(10)
        observed = {}

        def choose_adj_copy():
            msg = QApplication.activeModalWidget()
            self.assertIsInstance(msg, QMessageBox)
            observed["buttons"] = [button.text() for button in msg.buttons()]
            for button in msg.buttons():
                if button.text() == "_&adj Copy":
                    button.click()
                    return
            self.fail("Adjusted-copy button was not present")

        QTimer.singleShot(0, choose_adj_copy)
        self.assertTrue(self.board.apply_and_save())

        self.assertCountEqual(
            observed["buttons"],
            ["&Overwrite", "Save &As...", "_&adj Copy", "&Cancel"],
        )
        self.assertTrue(os.path.isfile(os.path.join(self.temp_dir.name, "image_adj.png")))

    def test_navigation_prompt_supports_plain_discard_and_session_memory(self):
        self.board.sliders["Brightness"].setValue(10)

        def discard():
            msg = QApplication.activeModalWidget()
            self.assertIsInstance(msg, QMessageBox)
            msg.checkBox().setChecked(True)
            QTest.keyClick(msg, Qt.Key.Key_D)

        QTimer.singleShot(0, discard)
        self.assertTrue(self.board.confirm_navigation())
        self.assertEqual(AdjustBoard._session_navigation_choice, "discard")

        self.board.sliders["Brightness"].setValue(20)
        self.assertTrue(self.board.confirm_navigation())

    def test_enter_does_not_save_and_o_invokes_save(self):
        enter_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        o_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_O,
            Qt.KeyboardModifier.NoModifier,
            "o",
        )
        with patch.object(self.board, "apply_and_save", return_value=True) as save:
            self.board.keyPressEvent(enter_event)
            save.assert_not_called()
            self.board.keyPressEvent(o_event)
            save.assert_called_once()

    def test_manual_zoom_survives_preview_refresh_and_fit_restores_fit_mode(self):
        self.board.actual_size()
        self.assertEqual(self.board.zoom_mode, "manual")
        self.assertAlmostEqual(self.board.view.transform().m11(), 1.0)
        self.board.zoom_in()
        zoom_scale = self.board.view.transform().m11()

        self.board.sliders["Brightness"].setValue(15)
        self.board.apply_preview_adjustments()

        self.assertEqual(self.board.zoom_mode, "manual")
        self.assertAlmostEqual(self.board.view.transform().m11(), zoom_scale)
        self.board.fit_preview()
        self.assertEqual(self.board.zoom_mode, "fit")

    def test_keypad_zoom_keys_use_preview_zoom_actions(self):
        self.board.actual_size()
        plus_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Plus,
            Qt.KeyboardModifier.KeypadModifier,
            "+",
        )
        self.board.keyPressEvent(plus_event)
        self.assertAlmostEqual(self.board.view.transform().m11(), 1.10)

        actual_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Slash,
            Qt.KeyboardModifier.KeypadModifier,
            "/",
        )
        self.board.keyPressEvent(actual_event)
        self.assertAlmostEqual(self.board.view.transform().m11(), 1.0)

    def test_control_mouse_wheel_zooms_without_navigating(self):
        def wheel_event(delta):
            event = MagicMock()
            event.type.return_value = QEvent.Type.Wheel
            event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
            event.angleDelta.return_value.y.return_value = delta
            return event

        with (
            patch.object(self.board, "zoom_in") as zoom_in,
            patch.object(self.board, "zoom_out") as zoom_out,
            patch.object(self.board, "open_adjacent_image") as navigate,
        ):
            up = wheel_event(120)
            self.assertTrue(self.board.eventFilter(self.board.view.viewport(), up))
            zoom_in.assert_called_once_with()
            navigate.assert_not_called()
            up.accept.assert_called_once_with()

            down = wheel_event(-120)
            self.assertTrue(self.board.eventFilter(self.board.view.viewport(), down))
            zoom_out.assert_called_once_with()
            navigate.assert_not_called()
            down.accept.assert_called_once_with()

    def test_initial_show_refits_preview_after_layout(self):
        self.board.show()
        QTest.qWait(20)
        mapped = self.board.view.transform().mapRect(
            self.board.pixmap_item.boundingRect()
        )
        viewport = self.board.view.viewport().rect()
        self.assertLessEqual(mapped.width(), viewport.width() + 2)
        self.assertLessEqual(mapped.height(), viewport.height() + 2)
        self.assertTrue(
            abs(mapped.width() - viewport.width()) <= 4 or
            abs(mapped.height() - viewport.height()) <= 4
        )
        self.assertEqual(self.board.minimumWidth(), 1120)


if __name__ == "__main__":
    unittest.main()
