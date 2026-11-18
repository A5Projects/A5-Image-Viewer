"""Full-resolution decoding policy, separate from background cache budgets."""

import math
import os
import warnings
from contextlib import contextmanager

from PIL import Image
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImageReader

from utils.file_ops import get_image_settings

MIB = 1024 * 1024
MAX_PREFETCH_IMAGE_BYTES = 256 * MIB

# Pillow may allocate a GIF disposal canvas during seek(), before a caller can
# inspect the next frame's size. Enforce the configured pixel ceiling there too.
warnings.filterwarnings("error", category=Image.DecompressionBombWarning, module=r"^PIL\.Image$")


class ImageLoadError(Exception):
    pass


def apply_image_loading_settings():
    limit = get_image_settings()["max_decoded_image_mb"]
    QImageReader.setAllocationLimit(limit)
    # Pillow has its own pixel guard. Keep it consistent with our explicit
    # four-byte-per-pixel check, rather than disabling large-image protection.
    Image.MAX_IMAGE_PIXELS = limit * MIB // 4
    return limit


def check_image_size(width, height, limit_mb):
    required = width * height * 4
    if required > limit_mb * MIB:
        raise ImageLoadError(
            f"This image ({width:,} × {height:,}) requires approximately "
            f"{math.ceil(required / MIB):,} MiB of pixel memory. "
            f"Your limit is {limit_mb:,} MiB.\n\n"
            "Increase Maximum decoded image size in Settings → Resource Usage to allow this size."
        )


def _first_frame_size(reader, path):
    # Qt scans all GIF frames for reader.size(). Its decoder renders onto the
    # logical screen declared at the start of the file. Peek on the same device
    # used for decoding so a replacement file cannot invalidate the size check.
    if os.path.splitext(path)[1].lower() == ".gif" and reader.format() == b"gif":
        header = bytes(reader.device().peek(10))
        if len(header) < 10:
            raise ImageLoadError("Unable to open image: incomplete GIF header.")
        width = int.from_bytes(header[6:8], "little")
        height = int.from_bytes(header[8:10], "little")
        if not width or not height:
            raise ImageLoadError("Unable to open image: GIF has no logical screen dimensions.")
        return QSize(width, height)
    return reader.size()


def read_full_image(path):
    limit = apply_image_loading_settings()
    reader = QImageReader(os.fspath(path))
    reader.setAutoTransform(False)
    try:
        size = _first_frame_size(reader, path)
        if size.isValid():
            check_image_size(size.width(), size.height(), limit)
            effective_limit = QImageReader.allocationLimit()
            if 0 < effective_limit < limit:
                try:
                    check_image_size(size.width(), size.height(), effective_limit)
                except ImageLoadError as error:
                    raise ImageLoadError(
                        "The QT_IMAGEIO_MAXALLOC environment variable limits image "
                        f"decoding to {effective_limit} MiB. Raise or remove that "
                        "override and restart the application."
                    ) from error
        image = reader.read()
        if image.isNull():
            raise ImageLoadError(f"Unable to open image: {reader.errorString()}")
        return image
    finally:
        # Release the Windows file handle even when an exception is retained.
        reader.setFileName("")


@contextmanager
def open_limited_pil_image(path, limit):
    # Some Pillow codecs allocate a canvas inside Image.open(). Probe the header
    # first, and recheck the opened image in case the file changed.
    reader = QImageReader(os.fspath(path))
    try:
        size = _first_frame_size(reader, path)
        if size.isValid():
            check_image_size(size.width(), size.height(), limit)
    finally:
        reader.setFileName("")
    try:
        with Image.open(path) as image:
            check_image_size(image.width, image.height, limit)
            yield image
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ImageLoadError(
            f"This image exceeds the {limit:,} MiB decoded-image limit. "
            "Increase Maximum decoded image size in Settings → Resource Usage, "
            "then open the image again."
        ) from error


def read_pil_image(path, *, png_text=None):
    limit = apply_image_loading_settings()
    try:
        with open_limited_pil_image(path, limit) as image:
            mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            pixels = image.convert(mode)
            if png_text is not None and image.format == "PNG":
                png_text.update(image.text)
            return pixels
    except (OSError, ValueError) as error:
        raise ImageLoadError(f"Unable to open image: {error}") from error
    except MemoryError as error:
        raise ImageLoadError(
            "Not enough memory to decode this image. Close other images or "
            "applications and try again."
        ) from error
