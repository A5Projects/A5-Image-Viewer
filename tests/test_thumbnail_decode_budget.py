import gc
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, Timer
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage, QImageReader
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QWidget

from ui.thumbnail_decode import ThumbnailDecodeBudget, _prepare
from ui.thumbnail_view import (
    FolderPreviewQueue, FolderPreviewWorker, ThumbnailView, _read_folder_preview_image, _read_thumbnail_image,
)
from utils.image_loading import MIB


class ThumbnailDecodeBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_fast_folder_switches_use_one_pool_and_drop_obsolete_work(self):
        folders = [self.folder / str(n) for n in range(3)]
        for folder in folders:
            folder.mkdir()
            for n in range(4):
                Image.new("RGB", (64, 48), "red").save(folder / f"{n}.png")
        view = ThumbnailView()
        self.addCleanup(view.close)
        view.apply_resource_settings({"thumbnail_workers": 2})
        lock, both_started, release = Lock(), Event(), Event()
        active = peak = 0
        started = []

        def decode(path, target_size, queue):
            nonlocal active, peak
            with lock:
                started.append(Path(path).parent)
                active += 1
                peak = max(peak, active)
                if active == 2:
                    both_started.set()
            try:
                if Path(path).parent == folders[0]:
                    release.wait(5)
                return _read_thumbnail_image(path, target_size, queue)
            finally:
                with lock:
                    active -= 1

        with patch("ui.thumbnail_view._read_thumbnail_image", side_effect=decode):
            try:
                view.load_folder(str(folders[0]), show_folders=False)
                self.assertTrue(both_started.wait(3))
                view.load_folder(str(folders[1]), show_folders=False)
                QTest.qWait(40)
                view.load_folder(str(folders[2]), show_folders=False)
                QTest.qWait(40)
                self.assertEqual(started, [folders[0]] * 2)
            finally:
                release.set()
            deadline = time.monotonic() + 4
            while len(view.thumbnail_cache) != 4 and time.monotonic() < deadline:
                QTest.qWait(10)
        self.assertEqual(set(started), {folders[0], folders[2]})
        self.assertEqual(peak, 2)
        self.assertEqual(set(map(Path, view.thumbnail_cache)), set(folders[2].glob("*.png")))

    def test_grid_and_folder_tile_share_bytes_and_cancel_waiting_file(self):
        class ObservedBudget(ThumbnailDecodeBudget):
            def acquire(self, cost, queue, *, wait=True):
                if wait:
                    waiting.set()
                return super().acquire(cost, queue, wait=wait)

        waiting, reading, release = Event(), Event(), Event()
        budget = ObservedBudget(4, 4 * MIB)
        grid, mosaic = FolderPreviewQueue([], budget), FolderPreviewQueue([], budget)
        first, second = (str(self.folder / n) for n in ("first.png", "second.webp"))
        for path in (first, second):
            Image.new("RGB", (480, 400), "blue").save(path)
        original = QImageReader.read
        reads = []

        def read(reader):
            reads.append(os.path.normpath(reader.fileName()))
            if reads[-1] == first:
                reading.set()
                release.wait(5)
            return original(reader)

        with patch.object(QImageReader, "read", read), ThreadPoolExecutor(max_workers=2) as pool:
            try:
                first_read = pool.submit(_read_thumbnail_image, first, 100, grid)
                self.assertTrue(reading.wait(3))
                tile = pool.submit(_read_folder_preview_image, second, 100, 100, mosaic)
                self.assertTrue(waiting.wait(3))
                os.rename(second, self.folder / "free-to-rename.webp")
                mosaic.stop()
                self.assertTrue(tile.result(timeout=3).isNull())
                self.assertEqual(reads, [first])
            finally:
                release.set()
            self.assertFalse(first_read.result(timeout=3)[1].isNull())
        self.assertEqual(budget.active, 0)
        self.assertEqual(budget.bytes_in_use, 0)

    def test_native_jpeg_estimate_high_depth_and_single_oversize_decode(self):
        budget = ThumbnailDecodeBudget(2, 4 * MIB)
        queue = FolderPreviewQueue([], budget)
        baseline, progressive = [str(self.folder / name) for name in ("base.jpg", "progressive.jpg")]
        for path in (baseline, progressive):
            Image.new("RGB", (512, 512), "blue").save(path, progressive=path == progressive)
        for path in (baseline, progressive):
            reader, _, cost = _prepare(path, QSize(100, 100), False, budget)
            reader.setFileName("")
            if path == baseline:
                self.assertLessEqual(2 * cost, budget.byte_limit)
            else:
                self.assertGreater(cost, budget.byte_limit)
            self.assertFalse(_read_thumbnail_image(path, 100, queue)[1].isNull())
        png = str(self.folder / "16-bit.png")
        source = QImage(512, 512, QImage.Format.Format_RGBA64)
        source.fill(0)
        self.assertTrue(source.save(png))
        reader, _, cost = _prepare(png, QSize(100, 100), False, budget)
        reader.setFileName("")
        self.assertGreaterEqual(cost, 512 * 512 * 8)

    def test_destroying_view_stops_live_queues_before_the_pool_is_destroyed(self):
        Image.new("RGB", (20, 20)).save(self.folder / "image.png")
        view = ThumbnailView()
        view.load_folder(str(self.folder), show_folders=False)
        queue = view.task_queue
        # Keep a broken teardown from hanging the test process indefinitely.
        watchdog = Timer(3, queue.stop)
        watchdog.start()
        try:
            started = time.monotonic()
            sip.delete(view)
            self.assertFalse(queue.running)
            self.assertLess(time.monotonic() - started, 2.5)
        finally:
            watchdog.cancel()
            watchdog.join()

    def test_worker_can_finish_delivering_after_its_receiving_view_is_deleted(self):
        Image.new("RGB", (20, 20)).save(self.folder / "image.png")
        view = ThumbnailView()
        # Model a worker already past its cancellation check at dispatch time.
        worker = FolderPreviewWorker(
            FolderPreviewQueue([str(self.folder)]), 1, 100, {"png"},
            start_delay_ms=0, results=view.thumbnail_results,
        )
        delivered = QSignalSpy(worker.results.folder)
        sip.delete(view)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(worker.run).result(timeout=3)
        self.app.processEvents()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0][:2], [1, str(self.folder)])

    def test_collecting_a_parented_view_during_decode_disposes_both_pools(self):
        Image.new("RGB", (30, 20)).save(self.folder / "image.png")
        reading, release = Event(), Event()
        original = QImageReader.read

        def read(reader):
            reading.set()
            release.wait(4)
            return original(reader)

        def open_and_drop():
            parent = QWidget()
            parent.cycle = parent  # Exercise passive cyclic GC without a close event.
            view = ThumbnailView(parent)
            view.load_folder(str(self.folder))
            self.assertTrue(reading.wait(2))
            return view.task_queue, (view.thumbnail_pool, view.folder_pool)

        with patch.object(QImageReader, "read", read):
            try:
                queue, pools = open_and_drop()
                gc.collect()
                self.assertFalse(queue.running)
            finally:
                release.set()
            deadline = time.monotonic() + 3
            while not all(sip.isdeleted(pool) for pool in pools) and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertTrue(all(sip.isdeleted(pool) for pool in pools))
