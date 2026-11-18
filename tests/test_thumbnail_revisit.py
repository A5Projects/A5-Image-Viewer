import os
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui import thumbnail_view
from ui.convert_dialog import ConvertDialog
from ui.main_window import MainWindow
from ui.thumbnail_view import HEIGHT_ROLE, WIDTH_ROLE, ThumbnailView, _read_thumbnail_image
from utils import file_ops


class ThumbnailRevisitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.first = Path(directory.name) / "first"
        self.other = Path(directory.name) / "other"
        self.first.mkdir()
        self.other.mkdir()
        decoder = patch.object(thumbnail_view, "_read_thumbnail_image",
                               wraps=thumbnail_view._read_thumbnail_image)
        self.decode = decoder.start()
        self.addCleanup(decoder.stop)
        self.view = ThumbnailView()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.shutdown)
        self.view.apply_resource_settings({"thumbnail_workers": 1})

    def load(self, folder):
        self.view.load_folder(str(folder), show_folders=False)

    def wait_for_thumbnails(self, *paths):
        deadline = time.monotonic() + 5
        while True:
            missing = []
            for path in paths:
                item = self.view.item_for_path(str(path))
                if (item is None or not item.data(WIDTH_ROLE)
                        or self.view.iconSize() not in item.icon().availableSizes()):
                    missing.append(path.name)
            if not missing:
                return
            if time.monotonic() >= deadline:
                self.fail(f"Thumbnails did not appear at {self.view.iconSize()}: {missing}")
            QTest.qWait(10)

    def reads(self):
        return [(Path(path), size) for (path, size), _ in self.decode.call_args_list]

    def center_color(self, path):
        icon = self.view.item_for_path(str(path)).icon()
        image = icon.pixmap(self.view.iconSize()).toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2)

    def test_unchanged_revisit_restores_pixels_dimensions_and_label_without_decoding(self):
        photo = self.first / "alpha.png"
        Image.new("RGBA", (320, 160), (255, 0, 0, 96)).save(photo)
        other_photo = self.other / "other.png"
        Image.new("RGB", (40, 40), "blue").save(other_photo)
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [(photo, self.view.iconSize().width())])
        self.load(self.other)
        self.wait_for_thumbnails(other_photo)
        self.decode.reset_mock()

        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [])
        item = self.view.item_for_path(str(photo))
        self.assertEqual((item.data(WIDTH_ROLE), item.data(HEIGHT_ROLE)), (320, 160))
        self.assertEqual(item.text(), "320x160        PNG\nalpha.png")
        image = item.icon().pixmap(self.view.iconSize()).toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).getRgb(),
                         (255, 0, 0, 96))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_revisit_rescans_and_decodes_only_changed_and_added_images(self):
        changed = self.first / "changed.bmp"
        kept = self.first / "kept.png"
        removed = self.first / "removed.png"
        added = self.first / "added.png"
        Image.new("RGB", (64, 64), "red").save(changed)
        # At this exact second, a 100 ns NTFS tick is below float mtime precision.
        stamp = 1_700_000_000_000_000_000
        os.utime(changed, ns=(stamp, stamp))
        before = changed.stat()
        for path in (kept, removed):
            Image.new("RGB", (40, 40), "green").save(path)
        self.load(self.first)
        self.wait_for_thumbnails(changed, kept, removed)
        self.load(self.other)
        Image.new("RGB", (64, 64), "blue").save(changed)
        os.utime(changed, ns=(stamp, stamp + 100))
        if changed.stat().st_mtime_ns == before.st_mtime_ns:
            # Filesystems with coarser timestamps still exercise size-preserving edits.
            os.utime(changed, ns=(stamp, stamp + 2_000_000_000))
        self.assertNotEqual(changed.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(changed.stat().st_size, before.st_size)
        removed.unlink()
        Image.new("RGB", (24, 24), "yellow").save(added)
        self.decode.reset_mock()

        self.load(self.first)
        self.wait_for_thumbnails(changed, kept, added)
        self.assertCountEqual(self.view.visible_image_paths(), map(str, (changed, kept, added)))
        size = self.view.iconSize().width()
        self.assertCountEqual(self.reads(), [(changed, size), (added, size)])
        self.assertEqual(self.center_color(changed).name(), "#0000ff")

    def test_thumbnail_size_change_regenerates_current_and_revisited_images(self):
        photo = self.first / "wide.png"
        Image.new("RGB", (400, 200), "green").save(photo)
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.decode.reset_mock()

        self.view.set_thumbnail_size(128)
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [(photo, 128)])
        self.load(self.other)
        self.assertEqual(self.view.thumbnail_model.rowCount(), 0)
        self.decode.reset_mock()
        self.view.set_thumbnail_size(240)
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [(photo, 240)])

    def test_keep_date_conversion_replaces_thumbnail_in_another_visited_folder(self):
        config = patch.object(file_ops, "CONFIG_FILE", str(self.first.parent / "config.json"))
        config.start()
        self.addCleanup(config.stop)
        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.crop_prefetch_service.shutdown)
        self.addCleanup(window.transfer_coordinator.shutdown)
        self.addCleanup(window.thumbnail_view.shutdown)
        self.view = window.thumbnail_view

        source = self.first / "photo.bmp"
        target = self.other / source.name
        kept = self.other / "kept.png"
        Image.new("RGB", (64, 64), "red").save(source)
        Image.new("RGB", (64, 64), "blue").save(target)
        Image.new("RGB", (40, 40), "green").save(kept)
        stamp = 1_700_000_000_000_000_000
        for path in (source, target):
            os.utime(path, ns=(stamp, stamp))
        original = target.stat()
        self.load(self.other)
        self.wait_for_thumbnails(target, kept)
        self.load(self.first)
        self.wait_for_thumbnails(source)
        window.current_folder_path = str(self.first)
        window.select_image_by_path(str(source), update_preview=False)

        def execute_conversion(dialog):
            dialog.radio_custom.setChecked(True)
            dialog.custom_folder_edit.setText(str(self.other))
            dialog.appendix_edit.clear()
            dialog.rotate_combo.setCurrentIndex(dialog.rotate_combo.findData("180"))
            dialog.keep_date_cb.setChecked(True)
            dialog.start_conversion()
            self.assertIsNotNone(dialog.worker)
            self.assertTrue(dialog.worker.wait(5000))
            self.app.processEvents()
            return dialog.result()

        with (patch.object(ConvertDialog, "exec", execute_conversion),
              patch.object(ConvertDialog, "confirm_overwrite_warning", return_value=True),
              patch("ui.convert_dialog.QMessageBox.information")):
            window.open_convert_dialog()

        self.assertEqual(target.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(target.stat().st_size, original.st_size)
        self.decode.reset_mock()
        self.load(self.other)
        self.wait_for_thumbnails(target, kept)
        self.assertEqual(self.reads(), [(target, self.view.iconSize().width())])
        self.assertEqual(self.center_color(target).name(), "#ff0000")

    @unittest.skipUnless(os.name == "nt", "Windows file dialog path separators")
    def test_refresh_with_forward_slashes_replaces_a_warm_thumbnail(self):
        photo = self.first / "photo.bmp"
        Image.new("RGB", (64, 64), "red").save(photo)
        original = photo.stat()
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.load(self.other)
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.decode.reset_mock()

        Image.new("RGB", (64, 64), "blue").save(photo)
        os.utime(photo, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertNotEqual(photo.as_posix(), str(photo))
        self.view.request_thumbnail_refresh(photo.as_posix())
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [(photo, self.view.iconSize().width())])
        self.assertEqual(self.center_color(photo).name(), "#0000ff")

    def test_refresh_during_a_decode_rejects_the_old_pixels_before_display_or_reuse(self):
        photo = self.first / "photo.bmp"
        Image.new("RGB", (64, 64), "red").save(photo)
        original = photo.stat()
        read_old_pixels = Event()
        release_old_pixels = Event()

        def hold_first_read(path, target_size):
            result = _read_thumbnail_image(path, target_size)
            if not read_old_pixels.is_set():
                read_old_pixels.set()
                release_old_pixels.wait(5)
            return result

        self.decode.side_effect = hold_first_read
        self.load(self.first)
        displayed = []

        def observe_item(item):
            if item.data(WIDTH_ROLE):
                displayed.append(self.center_color(photo).name())

        self.view.thumbnail_model.itemChanged.connect(observe_item)
        try:
            self.assertTrue(read_old_pixels.wait(5), "Initial thumbnail read did not start")
            Image.new("RGB", (64, 64), "blue").save(photo)
            os.utime(photo, ns=(original.st_atime_ns, original.st_mtime_ns))
            self.view.request_thumbnail_refresh(str(photo))
        finally:
            release_old_pixels.set()
        self.wait_for_thumbnails(photo)
        self.view.thumbnail_model.itemChanged.disconnect(observe_item)
        self.assertNotIn("#ff0000", displayed)
        self.assertEqual(self.center_color(photo).name(), "#0000ff")
        self.assertEqual(self.reads(), [(photo, self.view.iconSize().width())] * 2)

        self.load(self.other)
        self.decode.reset_mock()
        self.load(self.first)
        self.wait_for_thumbnails(photo)
        self.assertEqual(self.reads(), [])
        # The restored opaque thumbnail can differ by a JPEG rounding step.
        color = self.center_color(photo)
        self.assertGreaterEqual(color.blue(), 250)
        self.assertLessEqual(max(color.red(), color.green()), 5)


if __name__ == "__main__":
    unittest.main()
