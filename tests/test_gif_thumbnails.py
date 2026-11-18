import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image
from PyQt6.QtCore import QSize
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.gif_playback import _GifStream
from ui.thumbnail_view import ThumbnailView


def make_gif(path, *, loop=0):
    options = {} if loop is None else {"loop": loop}
    Image.new("RGB", (32, 16), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (32, 16), "blue")],
        duration=[60, 110], **options)


class GifThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.view = ThumbnailView()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.shutdown)
        self.view.set_thumbnail_size(100)
        self.view.resize(360, 274)
        self.view.show()

    def wait_for(self, condition):
        deadline = time.monotonic() + 4
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for GIF playback state")
            QTest.qWait(10)

    def test_visible_gifs_animate_without_overwriting_static_thumbnail_or_locking_source(self):
        source = self.folder / "a.gif"
        make_gif(source)
        self.view.load_folder(str(self.folder))
        self.assertIsNone(self.view._gif_playback._thread)
        self.wait_for(lambda: str(source) in self.view.thumbnail_cache)
        item = self.view.item_for_path(str(source))
        original = item.icon().cacheKey()
        self.view.set_gif_playback(True)
        self.wait_for(lambda: str(source) in self.view._gif_icons)
        first = self.view._gif_icons[str(source)].cacheKey()
        self.wait_for(lambda: self.view._gif_icons[str(source)].cacheKey() != first)
        self.assertEqual(item.icon().cacheKey(), original)
        renamed = source.with_name("moved.gif")
        source.rename(renamed)
        renamed.unlink()
        self.view.set_gif_playback(False)
        self.assertFalse(self.view._gif_icons)
        self.assertFalse(self.view._gif_playback.sources)
        self.assertEqual(item.icon().cacheKey(), original)

    def test_scrolling_filtering_and_hiding_release_sources(self):
        for n in range(28):
            make_gif(self.folder / f"{n:02}.gif")
        self.view.set_gif_playback(True)
        with patch.object(_GifStream, "open", wraps=_GifStream.open) as opened:
            self.view.load_folder(str(self.folder))
            first = str(self.folder / "00.gif")
            last = str(self.folder / "27.gif")
            self.wait_for(lambda: first in self.view._gif_icons)
            self.assertNotIn(last, self.view._gif_playback.sources)
            self.assertNotIn(last, [call.args[0] for call in opened.call_args_list])
            self.view.scrollToBottom()
            self.wait_for(lambda: last in self.view._gif_icons)
            self.assertNotIn(first, self.view._gif_playback.sources)
            self.assertNotIn(first, self.view._gif_icons)
            self.view.set_filter_text("not-found")
            self.wait_for(lambda: not self.view._gif_playback.sources)
            self.assertFalse(self.view._gif_icons)
            self.view.set_filter_text("27.gif")
            self.wait_for(lambda: last in self.view._gif_icons)
            self.view.hide()
            self.assertFalse(self.view._gif_playback.sources)
            self.view.show()
            self.wait_for(lambda: last in self.view._gif_icons)

    def test_size_guard_single_frame_gifs_and_playback_count(self):
        source = self.folder / "finite.gif"
        make_gif(source, loop=1)
        stream, cost = _GifStream.open(str(source), QSize(50, 50), 2**20)
        self.assertEqual(stream.size, QSize(50, 25))
        colors = [stream.advance().pixelColor(0, 0).name() for _ in range(4)]
        self.assertEqual(colors, ["#ff0000", "#0000ff"] * 2)
        self.assertEqual(stream.plays, 0)
        self.assertEqual(_GifStream.open(str(source), QSize(50, 50), cost - 1), (None, cost))
        make_gif(source, loop=None)
        once, _ = _GifStream.open(str(source), QSize(), 2**20)
        once.advance()
        once.advance()
        self.assertEqual(once.plays, 0)
        data = bytearray(source.read_bytes())
        data[6:8] = (20).to_bytes(2, "little")
        source.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            _GifStream.open(str(source), QSize(), 2**20)
        Image.new("RGB", (32, 16), "red").save(source)
        with self.assertRaisesRegex(ValueError, "Single-frame"):
            _GifStream.open(str(source), QSize(), 2**20)
