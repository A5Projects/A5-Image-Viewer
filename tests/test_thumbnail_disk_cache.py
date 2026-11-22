import os
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui import thumbnail_view
from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog
from ui.thumbnail_disk_cache import ENTRY_OVERHEAD, THUMBNAIL_DB_FILENAME, ThumbnailDiskCache
from ui.thumbnail_history import CANONICAL_THUMBNAIL_SIZE, PackedThumbnail
from ui.thumbnail_view import HEIGHT_ROLE, WIDTH_ROLE, ThumbnailView
from utils import file_ops


class ThumbnailDiskCacheUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache_dir = Path(self.temp.name) / "cache"

    @staticmethod
    def make_packed_rgb(width, height, color):
        img = QImage(64, 64, QImage.Format.Format_RGB888)
        img.fill(QColor(color))
        return PackedThumbnail.pack(img, width, height)

    @staticmethod
    def make_packed_alpha(width, height):
        img = QImage(64, 32, QImage.Format.Format_RGBA8888)
        img.fill(QColor(255, 0, 0, 96))
        return PackedThumbnail.pack(img, width, height)

    def test_persistence_across_restart_for_jpeg_and_alpha_png(self):
        rgb_path = str(Path(self.temp.name) / "photos" / "opaque.jpg")
        alpha_path = str(Path(self.temp.name) / "photos" / "alpha.png")
        fp_rgb = (1234, 1_700_000_000_000_000_000, 1_700_000_000_000_000_000)
        fp_alpha = (5678, 1_700_000_000_123_456_700, 1_700_000_000_123_456_700)
        packed_rgb = self.make_packed_rgb(1200, 900, "#224488")
        packed_alpha = self.make_packed_alpha(640, 320)

        cache1 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        cache1.put(rgb_path, fp_rgb, CANONICAL_THUMBNAIL_SIZE, packed_rgb)
        cache1.put(alpha_path, fp_alpha, CANONICAL_THUMBNAIL_SIZE, packed_alpha)
        self.assertTrue(cache1.flush(timeout=3.0))
        cache1.close()

        cache2 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(cache2.close)
        got_rgb = cache2.get(rgb_path, fp_rgb, CANONICAL_THUMBNAIL_SIZE)
        got_alpha = cache2.get(alpha_path, fp_alpha, CANONICAL_THUMBNAIL_SIZE)
        self.assertEqual(got_rgb, packed_rgb)
        self.assertEqual(got_alpha, packed_alpha)

    def test_folder_metadata_lookup_and_discard_overlays(self):
        folder = Path(self.temp.name) / "album_100%"
        sibling = Path(self.temp.name) / "album_100%_backup"
        img_a = str(folder / "a.png")
        img_b = str(folder / "b.png")
        img_sib = str(sibling / "s.png")
        fp_a = (100, 200, 300)
        fp_b = (101, 201, 301)
        fp_sib = (102, 202, 302)
        packed_a = self.make_packed_rgb(800, 600, "red")
        packed_b = self.make_packed_rgb(1024, 768, "green")
        packed_sib = self.make_packed_rgb(512, 512, "blue")

        cache = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(cache.close)
        cache.put(img_a, fp_a, CANONICAL_THUMBNAIL_SIZE, packed_a)
        cache.put(img_b, fp_b, CANONICAL_THUMBNAIL_SIZE, packed_b)
        cache.put(img_sib, fp_sib, CANONICAL_THUMBNAIL_SIZE, packed_sib)

        # Visible immediately from pending overlay before flush.
        meta_pending = cache.get_folder_metadata(str(folder))
        self.assertEqual(len(meta_pending), 2)
        self.assertTrue(any(v == (fp_a, CANONICAL_THUMBNAIL_SIZE, 800, 600) for v in meta_pending.values()))
        self.assertTrue(any(v == (fp_b, CANONICAL_THUMBNAIL_SIZE, 1024, 768) for v in meta_pending.values()))

        self.assertTrue(cache.flush(timeout=3.0))
        cache.discard(img_a)
        self.assertIsNone(cache.get(img_a, fp_a, CANONICAL_THUMBNAIL_SIZE))
        meta_after_discard = cache.get_folder_metadata(str(folder))
        self.assertEqual(len(meta_after_discard), 1)
        self.assertEqual(next(iter(meta_after_discard.values())), (fp_b, CANONICAL_THUMBNAIL_SIZE, 1024, 768))

        cache.discard_tree(str(folder))
        self.assertEqual(cache.get_folder_metadata(str(folder)), {})
        self.assertIsNone(cache.get(img_b, fp_b, CANONICAL_THUMBNAIL_SIZE))
        self.assertEqual(cache.get(img_sib, fp_sib, CANONICAL_THUMBNAIL_SIZE), packed_sib)
        self.assertTrue(cache.flush(timeout=3.0))
        self.assertEqual(cache.get(img_sib, fp_sib, CANONICAL_THUMBNAIL_SIZE), packed_sib)

    def test_fingerprint_and_target_size_mismatch_misses(self):
        path = str(Path(self.temp.name) / "shot.png")
        fp = (1000, 2000, 3000)
        packed = self.make_packed_rgb(640, 480, "white")
        cache = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(cache.close)
        cache.put(path, fp, CANONICAL_THUMBNAIL_SIZE, packed)
        self.assertTrue(cache.flush(timeout=3.0))

        self.assertIsNone(cache.get(path, (1001, 2000, 3000), CANONICAL_THUMBNAIL_SIZE))
        self.assertIsNone(cache.get(path, (1000, 2001, 3000), CANONICAL_THUMBNAIL_SIZE))
        self.assertIsNone(cache.get(path, (1000, 2000, 3001), CANONICAL_THUMBNAIL_SIZE))
        self.assertIsNone(cache.get(path, fp, 128))
        self.assertIsNone(cache.get(path, None, CANONICAL_THUMBNAIL_SIZE))
        self.assertEqual(cache.get(path, fp, CANONICAL_THUMBNAIL_SIZE), packed)

    def test_size_cap_and_lru_eviction_on_put_and_set_limit(self):
        packed = self.make_packed_rgb(100, 100, "purple")
        entry_cost = ENTRY_OVERHEAD + len(packed.data)
        cache = ThumbnailDiskCache(str(self.cache_dir), int(entry_cost * 2.5))
        self.addCleanup(cache.close)
        paths = [str(Path(self.temp.name) / f"img_{i}.jpg") for i in range(4)]
        fp = (10, 20, 30)

        for path in paths[:3]:
            cache.put(path, fp, CANONICAL_THUMBNAIL_SIZE, packed)
        self.assertTrue(cache.flush(timeout=3.0))
        # Oldest entry evicted when exceeding 2.5 * entry_cost down to 90%.
        self.assertIsNone(cache.get(paths[0], fp, CANONICAL_THUMBNAIL_SIZE))
        self.assertEqual(cache.get(paths[2], fp, CANONICAL_THUMBNAIL_SIZE), packed)

        cache.put(paths[3], fp, CANONICAL_THUMBNAIL_SIZE, packed)
        self.assertTrue(cache.flush(timeout=3.0))
        self.assertEqual(cache.get(paths[3], fp, CANONICAL_THUMBNAIL_SIZE), packed)

        cache.set_limit(entry_cost)
        self.assertTrue(cache.flush(timeout=3.0))
        surviving = [p for p in paths if cache.get(p, fp, CANONICAL_THUMBNAIL_SIZE) is not None]
        self.assertEqual(surviving, [paths[3]])

    def test_corruption_recovery_never_raises_and_recovers(self):
        path = str(Path(self.temp.name) / "recover.jpg")
        fp = (50, 60, 70)
        packed = self.make_packed_rgb(300, 300, "orange")
        cache1 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        cache1.put(path, fp, CANONICAL_THUMBNAIL_SIZE, packed)
        cache1.close()

        db_file = self.cache_dir / THUMBNAIL_DB_FILENAME
        db_file.write_bytes(b"corrupted binary garbage" * 64)

        cache2 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(cache2.close)
        self.assertIsNone(cache2.get(path, fp, CANONICAL_THUMBNAIL_SIZE))
        self.assertTrue(cache2.flush(timeout=3.0))

        cache2.put(path, fp, CANONICAL_THUMBNAIL_SIZE, packed)
        self.assertTrue(cache2.flush(timeout=3.0))
        self.assertEqual(cache2.get(path, fp, CANONICAL_THUMBNAIL_SIZE), packed)

    def test_multi_instance_concurrent_read_write_and_clear(self):
        fp = (10, 20, 30)
        packed = self.make_packed_rgb(200, 200, "cyan")
        c1 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        c2 = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(c2.close)
        self.addCleanup(c1.close)
        errors = []

        def writer_worker(cache, offset):
            try:
                for i in range(25):
                    p = str(Path(self.temp.name) / f"shared_{offset + i}.jpg")
                    cache.put(p, fp, CANONICAL_THUMBNAIL_SIZE, packed)
                    cache.get(p, fp, CANONICAL_THUMBNAIL_SIZE)
                cache.flush(timeout=5.0)
            except Exception as exc:
                errors.append(exc)

        t1 = Thread(target=writer_worker, args=(c1, 0))
        t2 = Thread(target=writer_worker, args=(c2, 100))
        t1.start()
        t2.start()
        t1.join(timeout=6.0)
        t2.join(timeout=6.0)
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(errors, [])

        c1.clear()
        self.assertIsNone(c1.get(str(Path(self.temp.name) / "shared_0.jpg"), fp, CANONICAL_THUMBNAIL_SIZE))
        self.assertIsNone(c2.get(str(Path(self.temp.name) / "shared_100.jpg"), fp, CANONICAL_THUMBNAIL_SIZE))

    def test_lazy_creation_and_disabled_mode_create_no_files(self):
        lazy_dir = Path(self.temp.name) / "lazy"
        lazy = ThumbnailDiskCache(str(lazy_dir), 1024 * 1024, enabled=True)
        lazy.discard(str(Path(self.temp.name) / "missing.png"))
        lazy.discard_tree(str(Path(self.temp.name) / "missing_dir"))
        self.assertTrue(lazy.flush(timeout=1.0))
        lazy.close()
        self.assertFalse(lazy_dir.exists())

        off_dir = Path(self.temp.name) / "off"
        off = ThumbnailDiskCache(str(off_dir), 1024 * 1024, enabled=False)
        off.put(str(Path(self.temp.name) / "a.png"), (1, 2, 3), CANONICAL_THUMBNAIL_SIZE,
                self.make_packed_rgb(10, 10, "red"))
        self.assertTrue(off.flush(timeout=1.0))
        off.close()
        self.assertFalse(off_dir.exists())

    def test_disk_usage_and_clear_reclaim_space_and_release_handles(self):
        path = str(Path(self.temp.name) / "usage.jpg")
        cache = ThumbnailDiskCache(str(self.cache_dir), 10 * 1024 * 1024)
        self.addCleanup(cache.close)
        cache.put(path, (1, 2, 3), CANONICAL_THUMBNAIL_SIZE, self.make_packed_rgb(400, 400, "teal"))
        self.assertTrue(cache.flush(timeout=3.0))
        self.assertGreater(cache.disk_usage_bytes(), 0)
        cache.clear()
        self.assertEqual(cache.disk_usage_bytes(), 0)


class ThumbnailDiskCacheIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config.json"
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", str(self.config_path))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        file_ops.set_startup_behavior("empty")

    def make_view(self, settings=None):
        view = ThumbnailView()
        self.addCleanup(view.close)
        self.addCleanup(view.shutdown)
        view.apply_resource_settings({"thumbnail_workers": 1})
        view.apply_disk_cache_settings(settings or file_ops.get_disk_cache_settings())
        return view

    @staticmethod
    def wait_for_thumbnails(view, *paths):
        deadline = time.monotonic() + 5.0
        while True:
            missing = []
            for path in paths:
                item = view.item_for_path(str(path))
                if (
                    item is None
                    or not item.data(WIDTH_ROLE)
                    or view.iconSize() not in item.icon().availableSizes()
                ):
                    missing.append(Path(path).name)
            if not missing:
                return
            if time.monotonic() >= deadline:
                raise AssertionError(f"Timed out waiting for {missing} at {view.iconSize()}")
            QTest.qWait(10)

    def test_config_paths_defaults_validation_and_isolation(self):
        defaults = file_ops.get_disk_cache_settings()
        self.assertTrue(defaults["enabled"])
        self.assertEqual(defaults["max_mb"], file_ops.DEFAULT_DISK_CACHE_MB)
        self.assertEqual(defaults["custom_dir"], "")
        self.assertEqual(Path(defaults["effective_dir"]), self.config_path.parent / "cache")

        with patch.object(file_ops, "CONFIG_FILE", file_ops.default_config_file()):
            self.assertEqual(file_ops.resolve_disk_cache_dir(""), file_ops.default_disk_cache_dir())

        custom_dir = Path(self.temp.name) / "custom_cache"
        self.assertEqual(Path(file_ops.resolve_disk_cache_dir(str(custom_dir))), custom_dir)

        file_ops.save_config({
            "disk_cache_enabled": "yes",
            "disk_cache_max_mb": True,
            "disk_cache_dir": 123,
        })
        fallback = file_ops.get_disk_cache_settings()
        self.assertTrue(fallback["enabled"])
        self.assertEqual(fallback["max_mb"], file_ops.DEFAULT_DISK_CACHE_MB)
        self.assertEqual(fallback["custom_dir"], "")

        file_ops.save_config({"disk_cache_max_mb": 999999})
        self.assertEqual(file_ops.get_disk_cache_settings()["max_mb"], file_ops.DEFAULT_DISK_CACHE_MB)

    def test_disk_cache_persists_across_views_and_rescales_without_redecoding(self):
        photos = Path(self.temp.name) / "photos"
        photos.mkdir()
        alpha = photos / "alpha.png"
        wide = photos / "wide.jpg"
        Image.new("RGBA", (320, 160), (255, 0, 0, 96)).save(alpha)
        Image.new("RGB", (400, 200), "green").save(wide)

        view1 = self.make_view()
        view1.load_folder(str(photos), show_folders=False)
        self.wait_for_thumbnails(view1, alpha, wide)
        view1.shutdown()
        self.assertGreater(ThumbnailDiskCache.directory_usage_bytes(
            file_ops.get_disk_cache_settings()["effective_dir"]
        ), 0)

        with patch.object(
            thumbnail_view,
            "_read_thumbnail_image",
            wraps=thumbnail_view._read_thumbnail_image,
        ) as reader:
            view2 = self.make_view()
            view2.load_folder(str(photos), show_folders=False)
            self.wait_for_thumbnails(view2, alpha, wide)
            reader.assert_not_called()

            alpha_item = view2.item_for_path(str(alpha))
            self.assertEqual((alpha_item.data(WIDTH_ROLE), alpha_item.data(HEIGHT_ROLE)), (320, 160))
            self.assertEqual(alpha_item.text(), "320x160        PNG\nalpha.png")
            alpha_img = alpha_item.icon().pixmap(view2.iconSize()).toImage()
            self.assertEqual(
                alpha_img.pixelColor(alpha_img.width() // 2, alpha_img.height() // 2).getRgb(),
                (255, 0, 0, 96),
            )
            self.assertEqual(alpha_img.pixelColor(0, 0).alpha(), 0)

            view2.set_thumbnail_size(128)
            self.wait_for_thumbnails(view2, alpha, wide)
            self.assertEqual(view2.iconSize().width(), 128)
            reader.assert_not_called()

            view2.set_thumbnail_size(240)
            self.wait_for_thumbnails(view2, alpha, wide)
            self.assertEqual(view2.iconSize().width(), 240)
            reader.assert_not_called()
            wide_img = view2.item_for_path(str(wide)).icon().pixmap(view2.iconSize()).toImage()
            self.assertEqual((wide_img.width(), wide_img.height()), (240, 240))
            self.assertGreaterEqual(wide_img.pixelColor(120, 120).green(), 120)

    def test_invalidation_paths_update_disk_cache(self):
        photos = Path(self.temp.name) / "edit_photos"
        photos.mkdir()
        target = photos / "photo.bmp"
        Image.new("RGB", (64, 64), "red").save(target)
        stamp = target.stat()

        view1 = self.make_view()
        view1.load_folder(str(photos), show_folders=False)
        self.wait_for_thumbnails(view1, target)
        self.assertTrue(view1.disk_cache.flush(timeout=3.0))

        # Keep-date edit replaced via explicit refresh.
        Image.new("RGB", (64, 64), "blue").save(target)
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        view1.request_thumbnail_refresh(str(target))
        self.wait_for_thumbnails(view1, target)

        # Force-refresh overwrite of another keep-date edit.
        Image.new("RGB", (64, 64), "lime").save(target)
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        view1.load_folder(str(photos), show_folders=False, force=True)
        self.wait_for_thumbnails(view1, target)
        view1.shutdown()

        with patch.object(
            thumbnail_view,
            "_read_thumbnail_image",
            wraps=thumbnail_view._read_thumbnail_image,
        ) as reader:
            view2 = self.make_view()
            view2.load_folder(str(photos), show_folders=False)
            self.wait_for_thumbnails(view2, target)
            reader.assert_not_called()
            img = view2.item_for_path(str(target)).icon().pixmap(view2.iconSize()).toImage()
            center = img.pixelColor(img.width() // 2, img.height() // 2)
            self.assertGreaterEqual(center.green(), 245)
            self.assertLessEqual(max(center.red(), center.blue()), 10)

    def test_settings_dialog_disk_cache_controls_and_clear_action(self):
        photos = Path(self.temp.name) / "ui_photos"
        photos.mkdir()
        photo = photos / "one.png"
        Image.new("RGB", (64, 64), "red").save(photo)

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.transfer_coordinator.shutdown)
        self.addCleanup(window.crop_prefetch_service.shutdown)
        self.addCleanup(window.thumbnail_view.shutdown)

        window.navigate_to_folder(str(photos))
        self.wait_for_thumbnails(window.thumbnail_view, photo)
        self.assertTrue(window.thumbnail_view.disk_cache.flush(timeout=3.0))

        dialog = SettingsDialog(window)
        self.addCleanup(dialog.deleteLater)
        dialog.disk_cache_settings_changed.connect(window.apply_disk_cache_settings)
        dialog.clear_disk_cache_requested.connect(window.clear_disk_cache)

        self.assertTrue(dialog.disk_cache_check.isChecked())
        self.assertEqual(dialog.disk_cache_limit_spin.value(), 1024)
        self.assertEqual(dialog.disk_cache_dir_edit.text(), "")
        self.assertNotEqual(dialog.disk_cache_usage_label.text(), "Used: 0 B")

        dialog.disk_cache_check.setChecked(False)
        self.assertFalse(dialog.disk_cache_limit_spin.isEnabled())
        self.assertFalse(dialog.disk_cache_dir_edit.isEnabled())
        self.assertFalse(dialog.disk_cache_browse_btn.isEnabled())
        self.assertFalse(dialog.disk_cache_default_btn.isEnabled())
        dialog.disk_cache_check.setChecked(True)
        self.assertTrue(dialog.disk_cache_limit_spin.isEnabled())

        dialog.disk_cache_clear_btn.click()
        self.assertEqual(dialog.disk_cache_usage_label.text(), "Used: 0 B")
        self.assertEqual(window.thumbnail_view.disk_cache.disk_usage_bytes(), 0)

        custom_dir = Path(self.temp.name) / "custom_dir"
        dialog.disk_cache_limit_spin.setValue(512)
        dialog.disk_cache_dir_edit.setText(str(custom_dir))
        dialog.accept()

        saved = file_ops.get_disk_cache_settings()
        self.assertEqual(saved["max_mb"], 512)
        self.assertEqual(Path(saved["custom_dir"]), custom_dir)
        self.assertEqual(Path(window.thumbnail_view.disk_cache.cache_dir), custom_dir)
        self.assertEqual(window.thumbnail_view.disk_cache.byte_limit, 512 * 1024 * 1024)

        dialog2 = SettingsDialog(window)
        self.addCleanup(dialog2.deleteLater)
        dialog2.disk_cache_settings_changed.connect(window.apply_disk_cache_settings)
        dialog2.reset_disk_cache_dir()
        dialog2.accept()
        self.assertEqual(file_ops.get_disk_cache_settings()["custom_dir"], "")


if __name__ == "__main__":
    unittest.main()
