import os
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image
from PyQt6.QtCore import QItemSelectionModel, QTimer, Qt
from PyQt6.QtGui import QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from ui import thumbnail_view as thumbnails
from ui.thumbnail_decode import ThumbnailDecodeBudget
from ui.main_window import MainWindow
from ui.thumbnail_view import ThumbnailView, ThumbnailTaskQueue, PATH_ROLE
from tests.qt_wait import wait_until
from utils import file_ops


class ThumbnailLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = self.temp.name
        self.view = ThumbnailView()
        self.view.resize(700, 600)
        self.view.show()

    def tearDown(self):
        self.view.shutdown()
        self.view.close()
        self.temp.cleanup()

    def make_images(self, count):
        paths = []
        for number in range(count):
            path = os.path.join(self.folder, f"{number:04}.png")
            Image.new("RGB", (10, 8), "red").save(path)
            paths.append(path)
        return paths

    def load(self, **kwargs):
        self.view.load_folder(self.folder, show_folders=False, **kwargs)
        wait_until(lambda: not self.view.loading)

    def test_refresh_reuses_thumbnails_and_force_decodes_again(self):
        paths = self.make_images(8)
        with patch.object(thumbnails, "_read_thumbnail_image", wraps=thumbnails._read_thumbnail_image) as reader:
            self.load()
            wait_until(lambda: len(self.view.thumbnail_cache) == 8)
            items = [self.view.item_for_path(p) for p in paths]
            icons = [i.icon().cacheKey() for i in items]
            calls = reader.call_count
            queue = self.view.task_queue
            self.load(asynchronous=True)
            self.assertEqual(reader.call_count, calls)
            self.assertIs(self.view.task_queue, queue)
            self.view.load_folder(self.folder.replace("\\", "/"), show_folders=False, asynchronous=True)
            wait_until(lambda: not self.view.loading)
            self.assertEqual(reader.call_count, calls)
            self.assertEqual([i.icon().cacheKey() for i in items], icons)
            self.load(force=True, asynchronous=True)
            wait_until(lambda: len(self.view.thumbnail_cache) == 8)
            self.assertEqual(reader.call_count, calls + 8)
            self.assertEqual(set(self.view.visible_image_paths()), set(paths))

    def test_changed_added_removed_and_nanosecond_metadata(self):
        paths = self.make_images(4)
        self.load()
        wait_until(lambda: len(self.view.thumbnail_cache) == 4)
        original = self.view.item_for_path(paths[0])
        key = original.icon().cacheKey()
        self.view.setCurrentIndex(original.index())
        for path in paths[:2]:
            self.view.selectionModel().select(self.view.item_for_path(path).index(), QItemSelectionModel.SelectionFlag.Select)
        stat = os.stat(paths[1])
        os.utime(paths[1], ns=(stat.st_atime_ns, stat.st_mtime_ns + 100_000))
        os.remove(paths[3])
        added = os.path.join(self.folder, "new.PNG")
        Image.new("RGB", (11, 9), "blue").save(added)
        with patch.object(thumbnails, "_read_thumbnail_image", wraps=thumbnails._read_thumbnail_image) as reader:
            self.load(asynchronous=True)
            wait_until(lambda: len(self.view.thumbnail_cache) == 4)
            self.assertEqual({c.args[0] for c in reader.call_args_list}, {paths[1], added})
        self.assertIsNone(self.view.item_for_path(paths[3]))
        self.assertIs(self.view.item_for_path(paths[0]), original)
        self.assertEqual(original.icon().cacheKey(), key)
        self.assertEqual({i.data(PATH_ROLE) for i in self.view.selectedIndexes()}, set(paths[:2]))

    def test_async_revisit_uses_ram_and_force_bypasses_same_fingerprint(self):
        path = os.path.join(self.folder, "photo.bmp")
        Image.new("RGB", (20, 20), "red").save(path)
        with tempfile.TemporaryDirectory() as other, patch.object(
                thumbnails, "_read_thumbnail_image", wraps=thumbnails._read_thumbnail_image) as reader:
            self.load(asynchronous=True)
            wait_until(lambda: path in self.view.thumbnail_cache)
            self.view.load_folder(other, asynchronous=True)
            wait_until(lambda: not self.view.loading)
            reader.reset_mock()
            self.load(asynchronous=True)
            wait_until(lambda: path in self.view.thumbnail_cache)
            reader.assert_not_called()
            stat = os.stat(path)
            Image.new("RGB", (20, 20), "blue").save(path)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.load(force=True, asynchronous=True)
            wait_until(lambda: path in self.view.thumbnail_cache)
            reader.assert_called_once()
            pixels = self.view.item_for_path(path).icon().pixmap(self.view.iconSize()).toImage()
            self.assertEqual(pixels.pixelColor(pixels.width() // 2, pixels.height() // 2).name(), "#0000ff")

    def test_scroll_priorities_use_actual_filtered_layout_and_wrap(self):
        paths = self.make_images(180)
        with patch.object(self.view, "_start_thumbnail_workers"):
            self.load()
        self.view.set_filter_text("0")
        # Hide a non-contiguous subset so model row numbers differ from visual positions.
        for row in range(0, 180, 3):
            self.view.setRowHidden(row, True)
        self.view.visible_rows = [r for r in range(180) if not self.view.isRowHidden(r)]
        self.view.doItemsLayout()
        self.view.scrollTo(self.view.model().index(130, 0), self.view.ScrollHint.PositionAtTop)
        priority, cursor = self.view._viewport_priority()
        order = self.view.visible_rows
        background = [r for r in order[cursor:] + order[:cursor] if r not in priority]
        self.assertIn(130, priority)
        self.assertTrue(all(not self.view.isRowHidden(r) for r in priority + background))
        self.assertLess(len(priority), 20)
        self.assertGreater(background[0], max(priority))
        self.assertLess(background[-1], min(priority))
        self.assertEqual(set(priority + background), set(self.view.visible_rows))

    def test_refresh_preserves_scroll_anchor_after_insertion(self):
        paths = self.make_images(160)
        with patch.object(self.view, "_start_thumbnail_workers"):
            self.load()
            self.view.scrollTo(self.view.item_for_path(paths[100]).index(), self.view.ScrollHint.PositionAtTop)
            self.view.doItemsLayout()
            row = self.view._viewport_priority()[0][0]
            item = self.view.model().item(row)
            top = self.view.visualRect(item.index()).top()
            for n in range(3):
                Image.new("RGB", (5, 5)).save(os.path.join(self.folder, f"!new{n}.png"))
            self.load(asynchronous=True)
            self.assertEqual(self.view.visualRect(item.index()).top(), top)

    def test_scan_is_background_and_obsolete_result_is_ignored(self):
        self.make_images(2)
        entered, release = threading.Event(), threading.Event()
        real_scan = thumbnails.scan_folder
        def slow_scan(*args, **kwargs):
            if args[0] == self.folder:
                entered.set()
                release.wait(3)
            return real_scan(*args, **kwargs)
        with tempfile.TemporaryDirectory() as other, patch.object(thumbnails, "scan_folder", side_effect=slow_scan):
            try:
                self.view.load_folder(self.folder, asynchronous=True)
                wait_until(entered.is_set)
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                wait_until(lambda: bool(ticks))
                self.assertTrue(self.view.loading)
                self.view.load_folder(other, asynchronous=True)
                self.assertEqual(self.view.scan_pool.maxThreadCount(), 1)
                release.set()
                wait_until(lambda: not self.view.loading)
                self.app.processEvents()
                self.assertEqual(self.view.folder_path, other)
                self.assertEqual(self.view.model().rowCount(), 0)
            finally:
                release.set()

    def test_scan_error_retains_existing_thumbnails(self):
        self.make_images(2)
        self.load()
        wait_until(lambda: len(self.view.thumbnail_cache) == 2)
        errors = []
        self.view.folder_load_failed.connect(errors.append)
        with patch.object(thumbnails, "scan_folder", side_effect=PermissionError("test denied")):
            self.load(asynchronous=True)
        self.assertEqual(errors, ["test denied"])
        self.assertEqual(len(self.view.thumbnail_cache), 2)
        self.assertEqual(self.view.model().rowCount(), 2)

    def test_two_and_eight_workers_follow_latest_position(self):
        records = [(str(i), str(i), "png", 0, "image", 1) for i in range(100)]
        for workers in (2, 8):
            with self.subTest(workers=workers):
                queue = ThumbnailTaskQueue(records, range(100), max_awaiting=workers * 2,
                                           decode_budget=ThumbnailDecodeBudget(workers, 256 << 20))
                queue.request_rows(range(10), viewport=(range(100), 10))
                active = [queue.take_next()[0] for _ in range(workers)]
                new_rows = list(range(60, 75))
                queue.request_rows(new_rows, viewport=(range(100), 75))
                # Already-running decodes finish; every next worker gets the new location.
                for row in active:
                    queue.task_done(row, True)
                    queue.acknowledge(row, True)
                result = [queue.take_next()[0] for _ in range(workers)]
                self.assertEqual(result, new_rows[:workers])
                self.assertTrue(set(range(workers, 10)) <= queue.pending_rows)
                for r in result:
                    queue.task_done(r, True)
                    queue.acknowledge(r, True)
                for remaining in new_rows[workers:]:
                    self.assertEqual(queue.take_next(), (remaining, True))
                    queue.task_done(remaining, True)
                    queue.acknowledge(remaining, True)
                self.assertEqual(queue.take_next(), (75, False))
                queue.stop()

    def test_resource_worker_counts_and_foreground_pause(self):
        self.make_images(30)
        for workers in (2, 8):
            self.view.apply_resource_settings({"thumbnail_workers": workers, "thumbnail_cache_mb": 256})
            with self.view.opening_image():
                self.load(force=True)
                self.assertEqual(self.view.thumbnail_pool.maxThreadCount(), workers)
                self.assertEqual(self.view.decode_budget.workers, workers)
                self.assertTrue(self.view.task_queue.foreground_loading)
                QTest.qWait(30)
                self.assertEqual(len(self.view.thumbnail_cache), 0)
            wait_until(lambda: len(self.view.thumbnail_cache) == 30)

    def test_show_in_browser_finishes_after_async_folder_change(self):
        paths = self.make_images(1)
        with tempfile.TemporaryDirectory() as other, patch.object(file_ops, "CONFIG_FILE", os.path.join(other, "config.json")):
            file_ops.set_startup_behavior("empty")
            window = MainWindow()
            try:
                window.navigate_to_folder(other)
                wait_until(lambda: not window.thumbnail_view.loading)
                window.fullscreen_viewer.load_image(paths[0])
                self.assertTrue(window.sync_browser_to_viewed_image())
                wait_until(lambda: not window.thumbnail_view.loading)
                selected = window.thumbnail_view.currentIndex().data(PATH_ROLE)
                self.assertEqual(os.path.normpath(selected), os.path.normpath(paths[0]))
                self.assertIsNone(window._pending_browser_sync)
            finally:
                window.fullscreen_viewer.close()
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.transfer_coordinator.shutdown()
                window.close()

    def test_shortcuts_and_foreground_pause_are_wired(self):
        with patch.object(file_ops, "CONFIG_FILE", os.path.join(self.folder, "config.json")):
            file_ops.set_startup_behavior("empty")
            window = MainWindow()
            try:
                window.current_folder_path = self.folder
                shortcuts = {s.key().toString(): s for s in window.findChildren(QShortcut)}
                with patch.object(window, "load_current_folder") as load:
                    shortcuts["F5"].activated.emit()
                    load.assert_called_with(force=False)
                    shortcuts["Ctrl+F5"].activated.emit()
                    load.assert_called_with(force=True)
                with patch.object(window, "take_viewer_prefetch", return_value=None), patch.object(window, "schedule_viewer_prefetch"), patch.object(window.fullscreen_viewer, "load_image") as image:
                    image.side_effect = lambda *args: self.assertTrue(window.thumbnail_view.foreground_loading)
                    window.load_prefetched_fullscreen("test.png")
                    self.assertFalse(window.thumbnail_view.foreground_loading)
                    image.side_effect = RuntimeError("decoder failed")
                    with self.assertRaises(RuntimeError):
                        window.load_prefetched_fullscreen("test.png")
                    self.assertFalse(window.thumbnail_view.foreground_loading)
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.transfer_coordinator.shutdown()
                window.close()


if __name__ == "__main__":
    unittest.main()
