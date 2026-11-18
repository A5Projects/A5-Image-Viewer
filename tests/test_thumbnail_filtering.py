import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QItemSelectionModel, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QStandardItem
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from ui.thumbnail_view import EXT_ROLE, KIND_ROLE, PATH_ROLE, ThumbnailView
from utils import file_ops
from tests.qt_wait import wait_until


class ThumbnailFilteringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = ThumbnailView()
        self.add_item("P:/images/destination", "folder", "")
        self.add_item("P:/images/match.webp", "image", "webp")
        self.add_item("P:/images/other.jpg", "image", "jpg")
        self.add_item("P:/images/document.pdf", "image", "pdf")

    def tearDown(self):
        self.view.shutdown()
        self.view.close()

    def add_item(self, path, kind, extension):
        item = QStandardItem(os.path.basename(path))
        item.setData(path, PATH_ROLE)
        item.setData(kind, KIND_ROLE)
        item.setData(extension, EXT_ROLE)
        self.view.thumbnail_model.appendRow(item)
        self.view.register_item(item)

    def test_text_filter_keeps_enabled_folders_visible(self):
        self.view.set_kind_visibility(show_images=True, show_videos=False, show_folders=True)
        self.view.set_filter_text("webp")

        self.assertFalse(self.view.isRowHidden(0))
        self.assertFalse(self.view.isRowHidden(1))
        self.assertTrue(self.view.isRowHidden(2))
        self.assertEqual(self.view.visible_item_count, 2)

    def test_show_folders_toggle_still_hides_folders(self):
        self.view.set_filter_text("webp")
        self.view.set_kind_visibility(show_images=True, show_videos=False, show_folders=False)

        self.assertTrue(self.view.isRowHidden(0))
        self.assertFalse(self.view.isRowHidden(1))
        self.assertEqual(self.view.visible_item_count, 1)

    def test_pdf_visibility_is_independent_from_images(self):
        self.view.set_kind_visibility(
            show_images=False,
            show_pdfs=True,
            show_videos=False,
            show_folders=False,
        )
        self.assertTrue(self.view.isRowHidden(1))
        self.assertTrue(self.view.isRowHidden(2))
        self.assertFalse(self.view.isRowHidden(3))

        self.view.set_kind_visibility(
            show_images=True,
            show_pdfs=False,
            show_videos=False,
            show_folders=False,
        )
        self.assertFalse(self.view.isRowHidden(1))
        self.assertFalse(self.view.isRowHidden(2))
        self.assertTrue(self.view.isRowHidden(3))

    def test_multiple_terms_require_every_word_in_any_order(self):
        self.add_item("P:/images/krea2_scene_345.PNG", "image", "png")
        self.add_item("P:/images/345_scene_krea2.png", "image", "png")
        self.add_item("P:/images/krea2_scene_346.png", "image", "png")
        self.add_item("P:/images/krea2_scene_345.jpg", "image", "jpg")
        self.add_item("P:/krea2_345_png/other.png", "image", "png")
        self.view.set_filter_text("  PNG   KREA2\t345  ")
        visible = [row for row in range(self.view.thumbnail_model.rowCount())
                   if not self.view.isRowHidden(row)]
        self.assertEqual(visible, [0, 4, 5])
        self.assertEqual(self.view.visible_image_paths(), [
            "P:/images/krea2_scene_345.PNG", "P:/images/345_scene_krea2.png",
        ])

    def test_multiple_terms_match_normal_words_for_all_enabled_file_kinds(self):
        for name, kind, extension in (
            ("blue_sky.png", "image", "png"),
            ("sky_blue.TXT", "text", "txt"),
            ("blue_sky.pdf", "image", "pdf"),
            ("sky_blue.mp4", "video", "mp4"),
            ("blue_sea.txt", "text", "txt"),
        ):
            self.add_item("P:/images/" + name, kind, extension)
        self.view.set_kind_visibility(show_images=True, show_videos=True,
                                      show_pdfs=True, show_text=True, show_folders=False)
        self.view.set_filter_text("blue sky")
        visible = [row for row in range(self.view.thumbnail_model.rowCount())
                   if not self.view.isRowHidden(row)]
        self.assertEqual(visible, [4, 5, 6, 7])
        self.view.set_kind_visibility(show_folders=False, show_text=False, show_videos=False)
        self.assertEqual(self.view.visible_item_count, 2)

    def test_whitespace_only_restores_files_and_punctuation_is_literal(self):
        self.add_item("P:/images/photo[1]_final.png", "image", "png")
        self.add_item("P:/images/photo1_final.png", "image", "png")
        self.view.set_filter_text("[1] final")
        self.assertFalse(self.view.isRowHidden(4))
        self.assertTrue(self.view.isRowHidden(5))
        self.view.set_filter_text(" \t  ")
        self.assertEqual(self.view.visible_item_count, 6)

    def test_editable_image_snapshot_excludes_pdf(self):
        self.view.set_kind_visibility(
            show_images=True,
            show_pdfs=True,
            show_videos=False,
            show_folders=False,
        )
        self.assertEqual(
            self.view.visible_image_paths(editable_only=True),
            ["P:/images/match.webp", "P:/images/other.jpg"],
        )

    def test_folder_scan_uses_independent_pdf_toggle(self):
        self.view.thumbnail_model.clear()
        self.view.path_items.clear()
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = os.path.join(folder, "document.pdf")
            jpg_path = os.path.join(folder, "photo.jpg")
            for path in (pdf_path, jpg_path):
                with open(path, "wb"):
                    pass

            self.view.load_folder(
                folder,
                show_images=False,
                show_videos=False,
                show_folders=False,
                show_pdfs=True,
            )
            self.assertIsNotNone(self.view.item_for_path(pdf_path))
            self.assertIsNone(self.view.item_for_path(jpg_path))

            self.view.load_folder(
                folder,
                show_images=True,
                show_videos=False,
                show_folders=False,
                show_pdfs=False,
            )
            self.assertIsNone(self.view.item_for_path(pdf_path))
            self.assertIsNotNone(self.view.item_for_path(jpg_path))

    def test_video_item_shows_file_size_before_frame_extraction(self):
        self.view.thumbnail_model.clear()
        self.view.path_items.clear()
        with tempfile.TemporaryDirectory() as folder:
            video_path = os.path.join(folder, "iteration.mp4")
            with open(video_path, "wb") as video_file:
                video_file.truncate(25 * 1024 * 1024)

            self.view.load_folder(
                folder,
                show_images=False,
                show_videos=True,
                show_folders=False,
            )

            item = self.view.item_for_path(video_path)
            self.assertIsNotNone(item)
            self.assertEqual(item.text(), "25 MiB        MP4\niteration.mp4")


class FilteredBrowserActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = patch.object(file_ops, "CONFIG_FILE", os.path.join(temp.name, "config.json"))
        config.start()
        self.addCleanup(config.stop)
        file_ops.set_startup_behavior("empty")
        self.paths = [os.path.join(temp.name, name)
                      for name in ("a-keep.png", "b-drop.png", "c-keep.png")]
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        for path in self.paths:
            self.assertTrue(image.save(path))
        self.window = MainWindow()
        self.window.current_folder_path = temp.name
        self.window.load_current_folder()
        wait_until(lambda: not self.window.thumbnail_view.loading)
        self.window.show()
        self.window.activateWindow()
        self.view = self.window.thumbnail_view
        self.view.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.window.image_modified = False
        self.view.shutdown()
        self.window.crop_prefetch_service.shutdown()
        self.window.transfer_coordinator.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_filter_preserves_visible_selection_for_batch_clipboard_and_delete(self):
        a, b, c = self.paths
        self.window.select_image_by_path(b)
        for path in (c, a):
            self.view.selectionModel().select(
                self.view.item_for_path(path).index(), QItemSelectionModel.SelectionFlag.Select
            )
        self.window.filter_edit.setText("keep")
        self.assertEqual(self.view.currentIndex().data(PATH_ROLE), a)
        self.assertEqual(self.window.current_image_path, a)
        self.assertCountEqual([i.data(PATH_ROLE) for i in self.view.selectionModel().selectedIndexes()], [a, c])
        with patch("ui.main_window.ConvertDialog") as dialog:
            dialog.return_value.exec.return_value = False
            dialog.return_value.changed_paths = []
            self.window.open_convert_dialog()
            dialog.assert_called_once_with([a, c], self.window)
        with patch.object(QApplication, "clipboard") as clipboard:
            self.window.cut_to_clipboard()
            mime = clipboard.return_value.setMimeData.call_args.args[0]
            self.assertEqual([os.path.normpath(url.toLocalFile()) for url in mime.urls()], [a, c])
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                patch("ui.main_window.delete_files", return_value=True) as delete:
            QTest.keyClick(self.view, Qt.Key.Key_Delete)
            delete.assert_called_once_with([a, c], permanent=False)
        self.assertIsNotNone(self.view.item_for_path(b))

    def test_filter_cancel_preserves_edit_and_zero_matches_clear_all_targets(self):
        a, _, _ = self.paths
        self.window.select_image_by_path(a)
        self.window.rotate_image_90()
        pixels = self.window.modified_pixmap.cacheKey()
        with patch.object(self.window, "prompt_save_changes", return_value=False) as prompt:
            self.window.filter_edit.setText("KeEp")
            prompt.assert_not_called()
            self.window.filter_edit.setText("missing")
            prompt.assert_called_once_with()
        self.assertEqual(self.window.filter_edit.text(), "KeEp")
        self.assertEqual(self.view.currentIndex().data(PATH_ROLE), a)
        self.assertEqual(self.window.modified_pixmap.cacheKey(), pixels)
        self.assertTrue(self.window.image_modified)

        QTimer.singleShot(0, lambda: QTest.keyClick(QApplication.activeModalWidget(), Qt.Key.Key_D))
        self.window.filter_edit.setText("missing")
        self.assertFalse(self.view.currentIndex().isValid())
        self.assertIsNone(self.window.current_image_path)
        self.assertTrue(self.window.preview_viewer.pixmap_item.pixmap().isNull())
        self.assertEqual(self.window.file_operation_paths(), [])
        with patch.object(self.window.fullscreen_viewer, "load_image") as load, \
                patch("ui.main_window.QMessageBox.question") as confirm, \
                patch.object(QApplication, "clipboard") as clipboard:
            QTest.keyClick(self.view, Qt.Key.Key_Return)
            QTest.keyClick(self.view, Qt.Key.Key_Delete)
            self.window.copy_to_clipboard()
            load.assert_not_called()
            confirm.assert_not_called()
            clipboard.return_value.setMimeData.assert_not_called()
        self.window.filter_edit.clear()
        self.assertEqual(self.window.selected_file_paths(), [])


if __name__ == "__main__":
    unittest.main()
