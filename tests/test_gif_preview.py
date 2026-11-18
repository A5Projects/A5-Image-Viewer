import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtGui import QColor, QImageReader, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.gif_preview import GifPreviewViewer
from utils import file_ops, image_loading


class GifPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        config = patch.object(file_ops, "CONFIG_FILE", str(self.folder / "config.json"))
        config.start()
        self.addCleanup(config.stop)
        self.view = GifPreviewViewer()
        self.view.resize(320, 240)
        self.view.show()
        self.addCleanup(self.view.close)
        self.gif = self.folder / "loop.GIF"
        self.make_gif(self.gif)

    @staticmethod
    def make_gif(path, loop=0):
        opts = {} if loop is None else {"loop": loop}
        Image.new("RGB", (64, 48), "red").save(
            path, save_all=True, append_images=[Image.new("RGB", (64, 48), "blue")],
            duration=[60, 100], **opts,
        )

    def color(self):
        return self.view.pixmap_item.pixmap().toImage().pixelColor(0, 0)

    def wait_color(self, name):
        expected = QColor(name)
        deadline = time.monotonic() + 4
        while self.color() != expected and time.monotonic() < deadline:
            QTest.qWait(8)
        self.assertEqual(self.color(), expected)

    def test_opt_in_starts_selected_gif_and_disable_restores_still_without_resetting_zoom(self):
        self.assertTrue(self.view.load_image(str(self.gif)))
        self.assertIsNone(self.view._playback)
        self.assertEqual(self.color(), QColor("red"))
        self.view.actual_size()
        self.view.zoom_in()
        transform = self.view.transform()
        self.view.set_gif_playback(True)
        self.wait_color("blue")
        self.assertEqual(self.view.transform(), transform)
        self.view.set_gif_playback(False)
        self.assertEqual(self.color(), QColor("red"))
        QTest.qWait(200)
        self.assertEqual(self.color(), QColor("red"))
        self.assertEqual(self.view.transform(), transform)

    def test_prefetch_and_rename_work_and_release_the_file_during_playback(self):
        first = QPixmap(str(self.gif))
        self.view.set_source_pixmap(str(self.gif), first)
        self.view.set_gif_playback(True)
        self.wait_color("blue")
        renamed = self.gif.with_name("renamed.gif")
        self.gif.rename(renamed)
        self.view.rename_gif_source(self.gif, renamed)
        self.wait_color("blue")
        self.view.set_gif_playback_paused(True)
        self.assertEqual(self.color(), QColor("red"))
        self.view.set_gif_playback_paused(False)
        self.wait_color("blue")
        renamed.unlink()

    def test_hiding_stops_and_showing_restarts_only_the_current_selection(self):
        self.view.set_gif_playback(True)
        self.view.load_image(str(self.gif))
        self.wait_color("blue")
        self.view.hide()
        self.assertFalse(self.view._requested)
        self.view.show()
        self.wait_color("blue")
        self.view.clear_image()
        self.assertTrue(self.view.pixmap_item.pixmap().isNull())
        QTest.qWait(200)
        self.assertTrue(self.view.pixmap_item.pixmap().isNull())

    def test_static_edits_and_non_gif_selection_are_never_overlaid_by_old_frames(self):
        self.view.set_gif_playback(True)
        path = self.folder / "ordinary.png"
        Image.new("RGB", (64, 48), "magenta").save(path)
        self.view.load_image(str(path))
        self.assertIsNone(self.view._playback)
        self.view.load_image(str(self.gif))
        self.wait_color("blue")
        edited = QPixmap(64, 48)
        edited.fill(QColor("green"))
        self.view.set_pixmap(edited)
        self.view.set_gif_playback(False)
        self.view.set_gif_playback(True)
        QTest.qWait(200)
        self.assertEqual(self.color(), QColor("green"))
        self.view.load_image(str(self.gif))
        self.view.load_image(str(path))
        QTest.qWait(200)
        self.assertEqual(self.color(), QColor("magenta"))

    def test_once_only_and_malformed_gifs_keep_a_visible_preview(self):
        finite = self.folder / "finite.gif"
        self.make_gif(finite, loop=None)
        self.view.set_gif_playback(True)
        self.view.load_image(str(finite))
        self.wait_color("blue")
        QTest.qWait(280)
        self.assertEqual(self.color(), QColor("blue"))
        malformed = self.folder / "malformed.gif"
        malformed.write_bytes(b"invalid")
        self.assertFalse(self.view.load_image(str(malformed)))
        self.assertTrue(self.view.last_error)
        self.assertFalse(self.view._requested)

    def test_first_frame_opens_without_scanning_all_frames_and_obeys_image_limit(self):
        with patch.object(QImageReader, "size", side_effect=AssertionError("Scanned whole GIF")):
            self.assertTrue(self.view.load_image(self.gif))
            self.assertEqual(self.color(), QColor("red"))
            dimensions = (1024).to_bytes(2, "little") * 2
            payload = self.gif.read_bytes()
            self.gif.write_bytes(payload[:6] + dimensions + payload[10:])
            with patch.object(image_loading, "apply_image_loading_settings", return_value=1):
                with self.assertRaisesRegex(image_loading.ImageLoadError, "4 MiB"):
                    image_loading.read_full_image(self.gif)
            self.gif.unlink()

    def test_truncated_or_zero_sized_gif_reports_load_error_and_releases_file(self):
        self.view.set_gif_playback(True)
        for data in (b"GIF89a", b"GIF89a" + bytes(10)):
            self.gif.write_bytes(data)
            self.assertFalse(self.view.load_image(self.gif))
            self.assertTrue(self.view.last_error)
            self.gif.unlink()
