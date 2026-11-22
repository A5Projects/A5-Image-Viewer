"""Bounded, in-memory history of thumbnails from previously viewed folders."""

import os
import sys
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage

CANONICAL_THUMBNAIL_SIZE = 256


@dataclass(frozen=True, slots=True)
class PackedThumbnail:
    source_width: int
    source_height: int
    data: bytes

    @classmethod
    def pack(cls, image, source_width, source_height):
        if image.isNull():
            return None
        transparent = False
        if image.hasAlphaChannel():
            # A fully opaque RGBA image benefits from JPEG compression too.
            rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
            alpha = rgba.constBits().asstring(rgba.sizeInBytes())[3::4]
            transparent = alpha.count(255) != len(alpha)

        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return None
        image_format, quality = ("PNG", -1) if transparent else ("JPEG", 90)
        if not image.save(buffer, image_format, quality):
            return None
        return cls(source_width, source_height, bytes(buffer.data()))

    def image(self):
        return QImage.fromData(self.data)


@dataclass(slots=True)
class _Entry:
    fingerprint: tuple
    target_size: int
    thumbnail: PackedThumbnail
    cost: int


class ThumbnailHistory:
    # Includes the LRU node, fingerprint, encoded bytes object, and bookkeeping.
    _ENTRY_OVERHEAD = 512

    def __init__(self, byte_limit, *, on_discard=None, on_discard_tree=None):
        self._entries = OrderedDict()
        self._lock = Lock()
        self._byte_count = 0
        self._byte_limit = max(0, int(byte_limit))
        self._on_discard = on_discard
        self._on_discard_tree = on_discard_tree

    @property
    def byte_count(self):
        with self._lock:
            return self._byte_count

    @property
    def byte_limit(self):
        with self._lock:
            return self._byte_limit

    def set_limit(self, byte_limit):
        with self._lock:
            self._byte_limit = max(0, int(byte_limit))
            self._trim()

    def get(self, path, fingerprint, target_size):
        key = os.path.normcase(os.path.normpath(path))
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.fingerprint != fingerprint or entry.target_size != target_size:
                return None
            self._entries.move_to_end(key)
            return entry.thumbnail

    def put(self, path, fingerprint, target_size, thumbnail):
        if fingerprint is None or thumbnail is None:
            return
        key = os.path.normcase(os.path.normpath(path))
        cost = self._ENTRY_OVERHEAD + sys.getsizeof(key) + len(thumbnail.data)
        with self._lock:
            self._remove(key)
            if cost <= self._byte_limit:
                self._entries[key] = _Entry(fingerprint, target_size, thumbnail, cost)
                self._byte_count += cost
                self._trim()

    def discard(self, path):
        key = os.path.normcase(os.path.normpath(path))
        with self._lock:
            self._remove(key)
        if self._on_discard is not None:
            self._on_discard(path)

    def discard_tree(self, path):
        key = os.path.normcase(os.path.normpath(path))
        prefix = os.path.join(key, "")
        with self._lock:
            matches = [entry for entry in self._entries if entry == key or entry.startswith(prefix)]
            for entry in matches:
                self._remove(entry)
        if self._on_discard_tree is not None:
            self._on_discard_tree(path)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._byte_count = 0

    def _remove(self, key):
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._byte_count -= entry.cost

    def _trim(self):
        while self._byte_count > self._byte_limit:
            _, entry = self._entries.popitem(last=False)
            self._byte_count -= entry.cost
