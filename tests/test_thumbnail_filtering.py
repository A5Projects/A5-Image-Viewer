import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QStandardItem
from PyQt6.QtWidgets import QApplication

from ui.thumbnail_view import EXT_ROLE, KIND_ROLE, PATH_ROLE, ThumbnailView


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


if __name__ == "__main__":
    unittest.main()
