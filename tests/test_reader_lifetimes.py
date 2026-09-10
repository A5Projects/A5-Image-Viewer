import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.crop_board import _read_prefetch_image
from ui.thumbnail_view import (
    WIDTH_ROLE,
    ThumbnailView,
    _read_folder_preview_image,
)


class ReaderLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_image(self, folder, name, size=(320, 240)):
        path = os.path.join(folder, name)
        Image.new("RGB", size, "red").save(path)
        return path

    def test_paused_thumbnail_worker_releases_its_last_file(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.make_image(folder, "a.jpg")
            second = self.make_image(folder, "b.jpg")
            view = ThumbnailView()
            try:
                view.apply_resource_settings({
                    "thumbnail_workers": 1,
                    "thumbnail_cache_mb": 256,
                })
                view.load_folder(
                    folder,
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )

                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    first_item = view.item_for_path(first)
                    second_item = view.item_for_path(second)
                    if (
                        first_item is not None and first_item.data(WIDTH_ROLE) and
                        second_item is not None and second_item.data(WIDTH_ROLE)
                    ):
                        break
                    QTest.qWait(20)
                else:
                    self.fail("Thumbnail worker did not finish in time.")

                view.set_background_activity_paused(True)
                renamed = os.path.join(folder, "renamed.jpg")
                os.rename(second, renamed)
                self.assertTrue(os.path.exists(renamed))
            finally:
                view.shutdown()
                view.close()

    def test_crop_prefetch_reader_releases_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.make_image(folder, "prefetch.jpg")
            self.assertIsNotNone(_read_prefetch_image(source, 32 * 1024 * 1024))
            renamed = os.path.join(folder, "prefetch-renamed.jpg")
            os.rename(source, renamed)
            self.assertTrue(os.path.exists(renamed))

    def test_folder_preview_reader_releases_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.make_image(folder, "preview.jpg")
            image = _read_folder_preview_image(source, 100, 100)
            self.assertFalse(image.isNull())
            renamed = os.path.join(folder, "preview-renamed.jpg")
            os.rename(source, renamed)
            self.assertTrue(os.path.exists(renamed))


if __name__ == "__main__":
    unittest.main()
