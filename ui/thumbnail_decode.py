"""Admission for thumbnail decodes shared by the grid and its folder mosaics."""

from io import BytesIO
from threading import Condition

from PIL import Image
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QImage, QImageIOHandler, QImageReader

from utils.image_loading import MIB, _first_frame_size


class ThumbnailDecodeBudget:
    def __init__(self, workers, cache_bytes):
        self.condition = Condition()
        self.active = 0
        self.bytes_in_use = 0
        self.paused = False
        self.configure(workers, cache_bytes)

    def configure(self, workers, cache_bytes):
        with self.condition:
            self.workers = workers
            self.byte_limit = min(cache_bytes // 4, 512 * MIB)
            self.condition.notify_all()

    def _available(self, cost):
        # Let a single large source that Qt can decode run by itself.
        return not self.paused and self.active < self.workers and (
            self.active == 0 or self.bytes_in_use + cost <= self.byte_limit)

    def set_paused(self, paused):
        with self.condition:
            self.paused = paused
            self.condition.notify_all()

    def acquire(self, cost, queue, *, wait=True):
        with self.condition:
            while queue.running and not self._available(cost):
                if not wait:
                    return False
                self.condition.wait()
            if not queue.running:
                return False
            self.active += 1
            self.bytes_in_use += cost
            return True

    def release(self, cost):
        with self.condition:
            self.active -= 1
            self.bytes_in_use -= cost
            self.condition.notify_all()

    def wake(self):
        with self.condition:
            self.condition.notify_all()


def _baseline_jpeg(header):
    # Progressive JPEGs can retain full-resolution coefficient buffers. If
    # metadata doesn't fit in this bounded probe, budget the full raster too.
    try:
        with Image.open(BytesIO(header), formats=("JPEG",)) as image:
            return not image.info.get("progressive")
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        return False


def _prepare(path, bounds, fill, budget):
    reader = QImageReader(path)
    reader.setAutoTransform(False)
    jpeg_header = None
    if (budget and reader.format() == b"jpeg" and reader.device().pos() == 0):
        jpeg_header = reader.device().peek(65536)
    size = _first_frame_size(reader, path)
    if not size.isValid() or size.isEmpty():
        return reader, size, 0
    width, height = size.width(), size.height()
    target = size.scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio).expandedTo(QSize(1, 1))
    crop_pixels = 0
    if fill:
        # Crop before scaling. A very thin panorama must not produce a
        # many-thousand-pixel-wide intermediate just to fill one mosaic cell.
        crop_width = min(width, max(1, height * bounds.width() // bounds.height()))
        crop_height = min(height, max(1, width * bounds.height() // bounds.width()))
        if (crop_width, crop_height) != (width, height):
            reader.setClipRect(QRect((width - crop_width) // 2, (height - crop_height) // 2,
                                     crop_width, crop_height))
            crop_pixels = crop_width * crop_height
        target = bounds
    reader.setScaledSize(target)
    if budget is None:
        return reader, size, 0
    depth = QImage.toPixelFormat(reader.imageFormat()).bitsPerPixel()
    bytes_per_pixel = max(4, (depth + 7) // 8)
    source_bytes = (width * height + crop_pixels) * bytes_per_pixel
    if (jpeg_header and not crop_pixels and source_bytes > budget.byte_limit // budget.workers
            and reader.supportsOption(QImageIOHandler.ImageOption.ScaledSize)
            and _baseline_jpeg(bytes(jpeg_header))):
        # Qt's JPEG reader can downsample directly at 1/2, 1/4 or 1/8 scale.
        divisor = 1
        while (divisor < 8 and width // (2 * divisor) >= target.width()
               and height // (2 * divisor) >= target.height()):
            divisor *= 2
        source_bytes = ((width + divisor - 1) // divisor
                        * ((height + divisor - 1) // divisor) * bytes_per_pixel)
    return reader, size, source_bytes + target.width() * target.height() * bytes_per_pixel


def read_scaled_thumbnail(path, bounds, *, fill=False, queue=None):
    budget = queue.decode_budget if queue else None
    while queue is None or queue.running:
        reader, size, cost = _prepare(path, bounds, fill, budget)
        if size.isEmpty() or not budget:
            return size, QImage() if size.isEmpty() else reader.read()
        reopen = not budget.acquire(cost, queue, wait=False)
        if reopen:
            reader.setFileName("")  # Don't hold a Windows file lock while waiting.
            if not budget.acquire(cost, queue):
                return size, QImage()
        try:
            if reopen:
                if not queue.running:
                    return size, QImage()
                reader, size, updated_cost = _prepare(path, bounds, fill, budget)
                if updated_cost > cost:
                    continue  # The file changed. Reserve for its new dimensions.
            return size, reader.read() if queue.running and not size.isEmpty() else QImage()
        finally:
            budget.release(cost)
    return QSize(), QImage()
