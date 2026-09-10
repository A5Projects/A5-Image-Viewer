import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow

from ui.fullscreen_viewer import FullScreenViewer
from utils import file_ops


class FullscreenParent(QMainWindow):
    def __init__(self):
        super().__init__()
        self.flip_calls = 0
        self.program_paths = []
        self.editor_paths = []
        self.slideshow_paths = []
        self.ordered_moves = []
        self.ordered_move_result = True
        self.random_targets = []

    def flip_image_horizontal(self):
        self.flip_calls += 1

    def open_in_associated_program(self, path, parent_override=None):
        self.program_paths.append((path, parent_override))

    def open_in_associated_editor(self, path, parent_override=None):
        self.editor_paths.append((path, parent_override))

    def supports_associated_editor(self):
        return True

    def fullscreen_image_paths(self):
        return list(self.slideshow_paths)

    def navigate_fullscreen(self, direction):
        self.ordered_moves.append(direction)
        return self.ordered_move_result

    def navigate_fullscreen_to_path(self, path):
        self.random_targets.append(path)
        return True


class FullscreenHudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_config_file = file_ops.CONFIG_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        file_ops.CONFIG_FILE = os.path.join(self.temp_dir.name, "config.json")
        self.parent = FullscreenParent()
        self.viewer = FullScreenViewer(self.parent)

    def tearDown(self):
        self.viewer.close()
        self.parent.close()
        file_ops.CONFIG_FILE = self.original_config_file
        self.temp_dir.cleanup()

    def key_event(self, key, modifiers=Qt.KeyboardModifier.NoModifier, text=""):
        return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)

    def test_hud_shows_filename_format_and_current_pixmap_dimensions(self):
        path = os.path.join(self.temp_dir.name, "example.webp")
        self.viewer.set_current_image_path(path)
        self.viewer.set_display_pixmap(QPixmap(640, 480))

        self.assertTrue(self.viewer.hud_visible)
        self.assertIn("example.webp", self.viewer.hud_label.text())
        self.assertIn("WEBP  640 x 480", self.viewer.hud_label.text())

        self.viewer.set_display_pixmap(QPixmap(480, 640))
        self.assertIn("WEBP  480 x 640", self.viewer.hud_label.text())

    def test_ctrl_h_persists_while_plain_h_remains_flip(self):
        ctrl_h = self.key_event(
            Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier, "h"
        )
        self.assertTrue(self.viewer.handle_key_press(ctrl_h))
        self.assertFalse(self.viewer.hud_visible)
        self.assertFalse(file_ops.get_fullscreen_hud_visible())

        plain_h = self.key_event(Qt.Key.Key_H, text="h")
        self.assertTrue(self.viewer.handle_key_press(plain_h))
        self.assertEqual(self.parent.flip_calls, 1)
        self.assertFalse(self.viewer.hud_visible)

        second_viewer = FullScreenViewer(self.parent)
        try:
            self.assertFalse(second_viewer.hud_visible)
        finally:
            second_viewer.close()

    def test_path_change_refreshes_name_and_long_names_are_elided(self):
        self.viewer.viewer.resize(220, 180)
        long_name = "a" * 160 + ".png"
        self.viewer.set_current_image_path(os.path.join(self.temp_dir.name, long_name))
        self.viewer.set_display_pixmap(QPixmap(100, 50))

        displayed_name = self.viewer.hud_label.text().splitlines()[0]
        self.assertNotEqual(displayed_name, long_name)
        self.assertLess(len(displayed_name), len(long_name))

        self.viewer.set_current_image_path(os.path.join(self.temp_dir.name, "renamed.jpg"))
        self.assertIn("renamed.jpg", self.viewer.hud_label.text())
        self.assertIn("JPG  100 x 50", self.viewer.hud_label.text())

    def test_f3_and_f4_use_fullscreen_path(self):
        path = os.path.join(self.temp_dir.name, "current.png")
        self.viewer.set_current_image_path(path)

        self.viewer.handle_key_press(self.key_event(Qt.Key.Key_F3))
        self.viewer.handle_key_press(self.key_event(Qt.Key.Key_F4))

        self.assertEqual(self.parent.program_paths, [(path, self.viewer)])
        self.assertEqual(self.parent.editor_paths, [(path, self.viewer)])

    def test_copy_move_refocus_can_avoid_delayed_focus_retries(self):
        action = MagicMock()
        with (
            patch.object(self.viewer, "refocus") as refocus,
            patch.object(self.viewer, "refocus_later") as refocus_later,
        ):
            self.viewer._run_and_refocus(action, delayed=False)

        action.assert_called_once_with()
        refocus.assert_called_once_with()
        refocus_later.assert_not_called()

    def test_ctrl_a_selects_all_and_ctrl_c_copies_selected_pixels(self):
        pixmap = QPixmap(80, 60)
        pixmap.fill(Qt.GlobalColor.red)
        self.viewer.set_display_pixmap(pixmap)

        ctrl_a = self.key_event(
            Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a"
        )
        self.assertTrue(self.viewer.handle_key_press(ctrl_a))
        self.assertEqual(
            self.viewer.viewer.selection_rect(),
            pixmap.rect(),
        )

        self.viewer.viewer.selection_rect_item.setRect(QRectF(10, 12, 30, 20))
        self.viewer.viewer.selection_rect_item.update_handles_pos()
        ctrl_c = self.key_event(
            Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier, "c"
        )
        self.assertTrue(self.viewer.handle_key_press(ctrl_c))
        copied = QApplication.clipboard().pixmap()
        self.assertEqual((copied.width(), copied.height()), (30, 20))

    def test_pixel_copy_uses_whole_image_without_selection(self):
        pixmap = QPixmap(45, 35)
        pixmap.fill(Qt.GlobalColor.blue)
        self.viewer.set_display_pixmap(pixmap)

        self.viewer.copy_pixels()

        copied = QApplication.clipboard().pixmap()
        self.assertEqual((copied.width(), copied.height()), (45, 35))

    def test_pixmap_change_discards_selection(self):
        self.viewer.set_display_pixmap(QPixmap(80, 60))
        self.viewer.select_all_pixels()
        self.assertIsNotNone(self.viewer.viewer.selection_rect_item)

        self.viewer.set_display_pixmap(QPixmap(20, 10))

        self.assertIsNone(self.viewer.viewer.selection_rect_item)

    def test_first_fullscreen_image_is_refitted_after_show(self):
        path = os.path.join(self.temp_dir.name, "first.png")
        pixmap = QPixmap(1600, 900)
        pixmap.fill(Qt.GlobalColor.darkCyan)
        self.assertTrue(pixmap.save(path))

        with patch.object(
            self.viewer.viewer,
            "fit_to_window",
            wraps=self.viewer.viewer.fit_to_window,
        ) as fit_to_window:
            self.viewer.load_image(path)
            QApplication.processEvents()

        fit_to_window.assert_called()

    def test_5_sets_exact_200_percent_zoom_for_main_and_keypad_keys(self):
        pixmap = QPixmap(320, 240)
        pixmap.fill(Qt.GlobalColor.darkGreen)
        self.viewer.set_display_pixmap(pixmap)

        key_variants = (
            self.key_event(Qt.Key.Key_5, text="5"),
            self.key_event(
                Qt.Key.Key_5,
                Qt.KeyboardModifier.KeypadModifier,
                "5",
            ),
            self.key_event(
                Qt.Key.Key_Clear,
                Qt.KeyboardModifier.KeypadModifier,
            ),
        )
        for event in key_variants:
            self.viewer.viewer.resetTransform()
            self.viewer.viewer.scale(1.37, 1.37)

            self.assertTrue(self.viewer.handle_key_press(event))
            self.assertAlmostEqual(self.viewer.viewer.transform().m11(), 2.0)
            self.assertAlmostEqual(self.viewer.viewer.transform().m22(), 2.0)

    def test_right_click_opens_menu_signal_but_right_drag_does_not(self):
        requested_positions = []
        self.viewer.viewer.context_menu_requested.disconnect()
        self.viewer.viewer.context_menu_requested.connect(requested_positions.append)
        self.viewer.resize(300, 220)
        self.viewer.show()
        QApplication.processEvents()

        viewport = self.viewer.viewer.viewport()
        QTest.mouseClick(
            viewport,
            Qt.MouseButton.RightButton,
            pos=QPoint(40, 40),
        )
        self.assertEqual(len(requested_positions), 1)

        QTest.mousePress(
            viewport,
            Qt.MouseButton.RightButton,
            pos=QPoint(40, 40),
        )
        QTest.mouseMove(viewport, QPoint(100, 100))
        QTest.mouseRelease(
            viewport,
            Qt.MouseButton.RightButton,
            pos=QPoint(100, 100),
        )
        self.assertEqual(len(requested_positions), 1)

    def test_pause_toggles_slideshow_using_persisted_mode(self):
        current = os.path.join(self.temp_dir.name, "a.png")
        other = os.path.join(self.temp_dir.name, "b.png")
        self.parent.slideshow_paths = [current, other]
        self.viewer.set_current_image_path(current)
        self.viewer.set_slideshow_mode("random")

        pause = self.key_event(Qt.Key.Key_Pause)
        self.assertTrue(self.viewer.handle_key_press(pause))
        self.assertTrue(self.viewer.slideshow_timer.isActive())
        self.assertEqual(self.viewer.slideshow_mode, "random")
        self.assertEqual(self.viewer.slideshow_random_queue, [other])

        self.assertTrue(self.viewer.handle_key_press(pause))
        self.assertFalse(self.viewer.slideshow_timer.isActive())

        second_viewer = FullScreenViewer(self.parent)
        try:
            self.assertEqual(second_viewer.slideshow_mode, "random")
        finally:
            second_viewer.close()

    def test_ordered_slideshow_stops_at_directory_end(self):
        self.parent.ordered_move_result = False
        self.viewer.start_slideshow("ordered")

        self.viewer.advance_slideshow()

        self.assertEqual(self.parent.ordered_moves, [1])
        self.assertFalse(self.viewer.slideshow_timer.isActive())

    def test_random_slideshow_visits_each_queued_image_once(self):
        paths = [os.path.join(self.temp_dir.name, f"{name}.png") for name in "abc"]
        self.parent.slideshow_paths = paths
        self.viewer.set_current_image_path(paths[0])
        with patch("ui.fullscreen_viewer.random.shuffle"):
            self.viewer.start_slideshow("random")

        self.viewer.advance_slideshow()
        self.viewer.advance_slideshow()
        self.viewer.advance_slideshow()

        self.assertEqual(self.parent.random_targets, paths[1:])
        self.assertFalse(self.viewer.slideshow_timer.isActive())


if __name__ == "__main__":
    unittest.main()
