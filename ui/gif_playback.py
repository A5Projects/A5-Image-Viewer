"""Stream visible GIF frames off the GUI thread, independently of the still-image cache."""

import math
import os
from io import BytesIO
from time import monotonic

from PIL import Image
from PyQt6.QtCore import QObject, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage


def _gif_structure(data, width, height):
    """Check frame bounds before the decoder allocates disposal canvases. Skip compressed pixels."""
    data = memoryview(data)
    frames = 0
    offset = 13
    if data[10] & 128:
        offset += 3 << ((data[10] & 7) + 1)
    while offset < len(data):
        kind = data[offset]
        offset += 1
        if kind == 0x3B:  # trailer
            return frames
        if kind == 0x2C:  # image descriptor
            left = int.from_bytes(data[offset:offset + 2], "little")
            top = int.from_bytes(data[offset + 2:offset + 4], "little")
            w = int.from_bytes(data[offset + 4:offset + 6], "little")
            h = int.from_bytes(data[offset + 6:offset + 8], "little")
            if not w or not h or left + w > width or top + h > height:
                raise ValueError("GIF frame exceeds its logical screen")
            flags = data[offset + 8]
            offset += 10  # descriptor plus the LZW minimum code size
            if flags & 128:
                offset += 3 << ((flags & 7) + 1)
            frames += 1
        elif kind == 0x21:  # extension
            offset += 1  # extension label
        else:
            raise ValueError("Unexpected GIF record")
        while data[offset]:  # length-prefixed sub-blocks, terminated by zero
            offset += 1 + data[offset]
        offset += 1
    raise ValueError("Incomplete GIF")


class _GifStream:
    @classmethod
    def open(cls, path, target_size, remaining):
        with open(path, "rb") as source:
            header = source.read(13)
            if len(header) != 13 or header[:6] not in (b"GIF87a", b"GIF89a"):
                raise ValueError("Invalid GIF header")
            width = int.from_bytes(header[6:8], "little")
            height = int.from_bytes(header[8:10], "little")
            if not width or not height:
                raise ValueError("GIF has no pixels")
            size = os.fstat(source.fileno()).st_size
            output_size = (QSize(width, height).scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio)
                           if target_size.isValid() else QSize(width, height))
            output_size = output_size.expandedTo(QSize(1, 1))
            # Estimate the compressed snapshot, compositor/previous RGBA canvases,
            # then the scaled delivery frame, raw pixel buffer and detached QImage.
            cost = size + width * height * 12 + output_size.width() * output_size.height() * 12
            if cost > remaining:
                return None, cost
            source.seek(0)
            data = source.read(size + 1)
            if len(data) != size or data[:13] != header:
                raise ValueError("GIF changed during read")
        count = _gif_structure(data, width, height)
        if count < 2:
            raise ValueError("Single-frame GIF")
        return cls(data, output_size, count), cost

    def __init__(self, data, output_size, count):
        self.image = Image.open(BytesIO(data), formats=("GIF",))
        self.size = output_size
        self.count = count
        repeats = self.image.info.get("loop")
        self.plays = None if repeats == 0 else (repeats or 0) + 1
        self.frame = 0
        self.due = 0

    def advance(self):
        self.image.seek(self.frame)
        frame = self.image.convert("RGBA")
        width, height = self.size.width(), self.size.height()
        if frame.size != (width, height):
            frame = frame.resize((width, height), Image.Resampling.BILINEAR)
        image = QImage(frame.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.due = monotonic() + max(20, self.image.info.get("duration") or 100) / 1000
        self.frame = (self.frame + 1) % self.count
        if self.frame == 0 and self.plays is not None:
            self.plays -= 1
        return image


class _GifDecoder(QObject):
    updated = pyqtSignal(object, int)

    def __init__(self, max_players, byte_limit):
        super().__init__()
        self.max_players = max_players
        self.byte_limit = byte_limit
        self.active = {}
        self.done = set()
        self.costs = {}

    @pyqtSlot(object, QSize)
    def advance(self, sources, target_size):
        wanted = set(sources)
        self.active = {key: stream for key, stream in self.active.items() if key in wanted}
        self.costs = {key: cost for key, cost in self.costs.items() if key in wanted}
        self.done.intersection_update(wanted)
        remaining = self.byte_limit - sum(self.costs[key] for key in self.active)
        frames = {}
        # Open at most one new source per request so a viewport change can interrupt a queue.
        pending = [key for key in sources if key not in self.active and key not in self.done
                   and self.costs.get(key, 0) <= remaining]
        if pending and len(self.active) < self.max_players:
            key = pending.pop(0)
            try:
                stream, cost = _GifStream.open(key[0], target_size, remaining)
                self.costs[key] = cost
                if stream is not None:
                    self.active[key] = stream
            except Exception:
                # A broken GIF should leave its ordinary thumbnail/preview in place.
                self.done.add(key)

        now = monotonic()
        finished = False
        for key, stream in list(self.active.items()):
            if stream.due > now:
                continue
            try:
                frames[key] = stream.advance()
                if stream.plays != 0:
                    continue
            except Exception:
                frames[key] = None
            del self.active[key]
            self.done.add(key)
            finished = True

        delay = -1
        if finished or (pending and len(self.active) < self.max_players):
            delay = 0
        elif self.active:
            earliest = min(stream.due for stream in self.active.values())
            delay = max(0, math.ceil((earliest - monotonic()) * 1000))
        self.updated.emit(frames, delay)


class GifPlayback(QObject):
    """One decoder thread and one scheduled request for all the current sources."""
    frames_changed = pyqtSignal(object)
    _advance = pyqtSignal(object, QSize)

    def __init__(self, parent, *, max_players, byte_limit):
        super().__init__(parent)
        self.max_players = max_players
        self.byte_limit = byte_limit
        self.sources = {}
        self.target_size = QSize()
        self._token = 0
        self._thread = None
        self._decoder = None
        self._busy = False
        self._changed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._request)

    def set_sources(self, paths, target_size=QSize()):
        paths = tuple(dict.fromkeys(paths))
        if tuple(self.sources) == paths and self.target_size == target_size:
            return
        previous = self.sources if self.target_size == target_size else {}
        self._token += 1
        self.sources = {path: previous.get(path, self._token) for path in paths}
        self.target_size = QSize(target_size)
        self._schedule()

    def invalidate(self, path):
        if path in self.sources:
            self._token += 1
            self.sources[path] = self._token
            self._schedule()

    def clear(self):
        self.set_sources(())

    def _schedule(self):
        self._changed = True
        self._timer.stop()
        if not self._busy and (self.sources or self._thread is not None):
            self._request()

    def _request(self):
        if self._thread is None:
            if not self.sources:
                return
            self._thread = QThread(self)
            self._decoder = _GifDecoder(self.max_players, self.byte_limit)
            self._decoder.moveToThread(self._thread)
            self._thread.finished.connect(self._decoder.deleteLater)
            self._advance.connect(self._decoder.advance)
            self._decoder.updated.connect(self._updated)
            self._thread.start()
        self._busy = True
        self._changed = False
        self._advance.emit(tuple(self.sources.items()), self.target_size)

    @pyqtSlot(object, int)
    def _updated(self, frames, delay):
        if self._thread is None or self.sender() != self._decoder:
            return
        current = {path: image for (path, token), image in frames.items()
                   if self.sources.get(path) == token}
        if current:
            self.frames_changed.emit(current)
        self._busy = False
        if self._changed:
            self._request()
        elif delay >= 0 and self.sources:
            self._timer.start(delay)

    def shutdown(self):
        self.sources.clear()
        self._timer.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = self._decoder = None
        self._busy = False
