import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QElapsedTimer, QItemSelectionModel, QPoint, Qt, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.crop_board import CropBoard
from ui.thumbnail_view import PATH_ROLE
from utils import file_ops


class ViewerWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.folder = os.path.join(self.temp.name, "images")
        os.mkdir(self.folder)
        self.paths = [os.path.join(self.folder, name) for name in ("a.png", "b.png")]
        for path in self.paths:
            Image.new("RGB", (1200, 900), "blue").save(path)
        self.child = os.path.join(self.folder, "child")
        os.mkdir(self.child)
        self.window = MainWindow()
        self.app.processEvents()
        self.window.current_folder_path = self.folder
        self.window.thumbnail_view.load_folder(self.folder, show_folders=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.image_modified = False
        self.window.fullscreen_viewer.close()
        self.window.transfer_coordinator.shutdown()
        self.window.thumbnail_view.shutdown()
        self.window.crop_prefetch_service.shutdown()
        self.app.processEvents()
        self.window.close()
        self.config_patch.stop()
        self.temp.cleanup()

    def open_viewer(self):
        self.window.select_image_by_path(self.paths[0])
        self.window.open_current_thumbnail_fullscreen()
        self.app.processEvents()
        return self.window.fullscreen_viewer

    def test_gif_playback_settings_apply_to_current_selection_and_prefetched_images(self):
        path = os.path.join(self.folder, "animated.GIF")
        Image.new("RGB", (32, 16), "red").save(
            path, save_all=True, append_images=[Image.new("RGB", (32, 16), "lime")],
            loop=0, duration=80,
        )
        self.window.add_thumbnail_paths([path])
        preview = self.window.preview_viewer
        grid = self.window.thumbnail_view

        def change_settings(enabled, preview_only):
            def choose():
                dialog = self.app.activeModalWidget()
                dialog.animate_gifs_check.setChecked(enabled)
                dialog.gif_preview_only_check.setChecked(preview_only)
                dialog.accept()

            QTimer.singleShot(0, choose)
            self.window.open_settings_dialog()

        def preview_color():
            return preview.pixmap_item.pixmap().toImage().pixelColor(0, 0).name()

        def wait_for_green():
            timer = QElapsedTimer()
            timer.start()
            while timer.elapsed() < 2000 and preview_color() != "#00ff00":
                QTest.qWait(10)
            self.assertEqual(preview_color(), "#00ff00")

        self.assertEqual(preview_color(), "#ff0000")
        with patch.object(grid, "set_gif_playback", wraps=grid.set_gif_playback) as grid_setting:
            change_settings(True, True)
            grid_setting.assert_called_with(False)
            wait_for_green()
            change_settings(True, False)
            grid_setting.assert_called_with(True)
            self.window.select_image_by_path(self.paths[0])
            with patch.object(self.window, "take_viewer_prefetch", return_value=QImage(path)):
                self.window.select_image_by_path(path)
            wait_for_green()
            change_settings(False, False)
            grid_setting.assert_called_with(False)
        self.assertEqual(preview_color(), "#ff0000")

    def test_delete_key_includes_selected_folder(self):
        self.window.select_image_by_path(self.child)
        self.window.activateWindow()
        self.window.thumbnail_view.setFocus()
        self.app.processEvents()
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes) as confirm, patch("ui.main_window.delete_files", return_value=True) as delete:
            QTest.keyClick(self.window.thumbnail_view, Qt.Key.Key_Delete)
        delete.assert_called_once_with([self.child], permanent=False)
        self.assertIn("folder and its contents", confirm.call_args.args[2])
        self.assertIsNone(self.window.row_for_path(self.child))

    def test_mixed_folder_delete_cancel_and_permanent_flag(self):
        self.window.select_image_by_path(self.child)
        view = self.window.thumbnail_view
        index = view.model().indexFromItem(view.item_for_path(self.paths[0]))
        view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No), patch("ui.main_window.delete_files") as delete:
            self.window.delete_selected_files()
        delete.assert_not_called()
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), patch("ui.main_window.delete_files", return_value=True) as delete:
            self.window.delete_selected_files(permanent=True)
        delete.assert_called_once_with([self.child, self.paths[0]], permanent=True)

    def test_space_advances_and_backspace_syncs_without_changing_escape_anchor(self):
        viewer = self.open_viewer()
        QTest.keyClick(viewer.viewer, Qt.Key.Key_Space)
        self.assertEqual(viewer.current_image_path, self.paths[1])
        QTest.keyClick(viewer.viewer, Qt.Key.Key_Backspace)
        self.assertEqual(self.window.thumbnail_view.currentIndex().data(PATH_ROLE), self.paths[1])
        self.assertTrue(viewer.isVisible())
        self.assertEqual(self.window.fullscreen_start_path, self.paths[0])
        QTest.keyClick(viewer.viewer, Qt.Key.Key_Escape)
        self.assertEqual(self.window.thumbnail_view.currentIndex().data(PATH_ROLE), self.paths[0])

    def test_sync_menu_preserves_unsaved_pixels_and_enter_selection(self):
        viewer = self.open_viewer()
        self.window.navigate_fullscreen(1)
        self.window.rotate_image_90()
        self.assertTrue(self.window.image_modified)
        def choose_sync(menu, *args):
            next(action for action in menu.actions()
                 if action.text().startswith("Show in browser\t")).trigger()
        with patch.object(self.window, "prompt_save_changes") as prompt, \
                patch("ui.fullscreen_viewer.QMenu.exec", choose_sync):
            viewer.show_context_menu(QPoint(0, 0))
        prompt.assert_not_called()
        self.assertTrue(self.window.image_modified)
        self.assertEqual(self.window.preview_viewer.pixmap_item.pixmap().size(), viewer.viewer.pixmap_item.pixmap().size())
        self.window.image_modified = False
        QTest.keyClick(viewer.viewer, Qt.Key.Key_Return)
        self.assertEqual(self.window.thumbnail_view.currentIndex().data(PATH_ROLE), self.paths[1])

    def test_hud_stays_at_viewport_corner_during_pan_and_zoom(self):
        viewer = self.open_viewer()
        viewer.toggle_display_mode()
        viewer.showNormal()
        viewer.resize(600, 400)
        self.app.processEvents()
        viewer.viewer.zoom_200()
        before = viewer.hud_label.mapTo(viewer, QPoint(0, 0))
        viewer.viewer.horizontalScrollBar().setValue(viewer.viewer.horizontalScrollBar().value() + 130)
        viewer.viewer.verticalScrollBar().setValue(viewer.viewer.verticalScrollBar().value() + 95)
        viewer.viewer.zoom_in()
        self.app.processEvents()
        self.assertEqual(viewer.hud_label.mapTo(viewer, QPoint(0, 0)), before)
        self.assertEqual(before, viewer.viewer.viewport().mapTo(viewer, QPoint(12, 12)))
        self.assertTrue(viewer.hud_label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_crop_zoom_pan_selection_and_prefetch_navigation(self):
        board = CropBoard(self.paths[0], navigation_paths=self.paths)
        try:
            board.show()
            self.app.processEvents()
            board.select_all()
            rect = board.view.selection_rect_item.rect()
            board.view.actual_size()
            board.view.zoom_in()
            self.assertAlmostEqual(board.view.transform().m11(), 1.1)
            self.assertEqual(board.view.selection_rect_item.rect(), rect)
            self.assertFalse(board.has_unsaved_changes())
            viewport = board.view.viewport()
            before = board.view.horizontalScrollBar().value()
            QTest.mousePress(viewport, Qt.MouseButton.RightButton, pos=QPoint(200, 200))
            QTest.mouseMove(viewport, QPoint(250, 230))
            QTest.mouseRelease(viewport, Qt.MouseButton.RightButton, pos=QPoint(250, 230))
            self.assertNotEqual(board.view.horizontalScrollBar().value(), before)
            self.assertEqual(board.view.selection_rect_item.rect(), rect)
            image = QImage(self.paths[1])
            cost = image.sizeInBytes()
            board.prefetch_cache[self.paths[1]] = (board._fingerprint(self.paths[1]), image, cost)
            board.prefetch_cache_bytes = cost
            with patch("ui.crop_board.QImageReader") as reader:
                board.open_adjacent_image(1)
            reader.assert_not_called()
            self.assertEqual(board.image_path, self.paths[1])
            self.assertEqual(board.view.zoom_mode, "fit")
            self.assertIsNone(board.view.selection_rect_item)
            self.assertFalse(board.has_unsaved_changes())
        finally:
            board.close()
