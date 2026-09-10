import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.thumbnail_view import FolderPreviewQueue, FolderPreviewWorker, ThumbnailView


class FolderPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_worker(self, target_size=160):
        return FolderPreviewWorker(
            FolderPreviewQueue([]),
            generation=1,
            target_size=target_size,
            supported_formats={"png", "jpg"},
            entry_limit=200,
            start_delay_ms=0,
        )

    def test_builds_mosaic_from_at_most_four_direct_images(self):
        with tempfile.TemporaryDirectory() as folder:
            for index, color in enumerate(("red", "green", "blue", "yellow", "purple")):
                Image.new("RGB", (30 + index, 20), color).save(
                    os.path.join(folder, f"{index}.png")
                )
            preview = self.make_worker().build_preview(folder)
            self.assertIsNotNone(preview)
            self.assertEqual((preview.width(), preview.height()), (160, 160))

    def test_does_not_recurse_into_nested_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            nested = os.path.join(folder, "nested")
            os.mkdir(nested)
            Image.new("RGB", (20, 20), "red").save(os.path.join(nested, "image.png"))
            self.assertIsNone(self.make_worker().build_preview(folder))

    def test_empty_folder_keeps_generic_icon(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(self.make_worker().build_preview(folder))

    def test_thumbnail_view_admits_delayed_folder_preview(self):
        with tempfile.TemporaryDirectory() as parent:
            child = os.path.join(parent, "child")
            os.mkdir(child)
            Image.new("RGB", (30, 20), "red").save(os.path.join(child, "image.png"))
            view = ThumbnailView()
            try:
                view.load_folder(parent, show_images=True, show_videos=False, show_folders=True)
                deadline = time.monotonic() + 4.0
                while child not in view.thumbnail_cache and time.monotonic() < deadline:
                    QTest.qWait(50)
                self.assertIn(child, view.thumbnail_cache)
                self.assertEqual(view.thumbnail_cache[child][1], "folder")
            finally:
                view.shutdown()
                view.close()

    def test_folder_change_cancels_stale_preview(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            child = os.path.join(first, "child")
            os.mkdir(child)
            Image.new("RGB", (30, 20), "red").save(os.path.join(child, "image.png"))
            view = ThumbnailView()
            try:
                view.load_folder(first, show_images=True, show_videos=False, show_folders=True)
                view.load_folder(second, show_images=True, show_videos=False, show_folders=True)
                QTest.qWait(1400)
                self.assertNotIn(child, view.thumbnail_cache)
                self.assertIsNone(view.item_for_path(child))
            finally:
                view.shutdown()
                view.close()


if __name__ == "__main__":
    unittest.main()
