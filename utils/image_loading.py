"""Full-resolution decoding policy, separate from background cache budgets."""

import math

from PIL import Image
from PyQt6.QtGui import QImageReader

from utils.file_ops import get_image_settings

MIB = 1024 * 1024
MAX_PREFETCH_IMAGE_BYTES = 256 * MIB


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
            f"{math.ceil(required / MIB):,} MiB to decode. "
            f"Your limit is {limit_mb:,} MiB.\n\n"
            "Increase Maximum decoded image size in Settings → Resource Usage, "
            "then open the image again."
        )


def read_full_image(path):
    limit = apply_image_loading_settings()
    reader = QImageReader(path)
    reader.setAutoTransform(False)
    try:
        size = reader.size()
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


def read_pil_image(path):
    limit = apply_image_loading_settings()
    # Qt can inspect the header without triggering Pillow's pixel guard first.
    reader = QImageReader(path)
    try:
        size = reader.size()
        if size.isValid():
            check_image_size(size.width(), size.height(), limit)
    finally:
        reader.setFileName("")
    try:
        with Image.open(path) as image:
            check_image_size(image.width, image.height, limit)
            mode = "RGBA" if (image.mode in ("RGBA", "LA") or
                              (image.mode == "P" and "transparency" in image.info)) else "RGB"
            return image.convert(mode)
    except Image.DecompressionBombError as error:
        raise ImageLoadError(
            f"This image exceeds the {limit:,} MiB decoded-image limit. "
            "Increase Maximum decoded image size in Settings → Resource Usage, "
            "then open the image again."
        ) from error
    except (OSError, ValueError) as error:
        raise ImageLoadError(f"Unable to open image: {error}") from error
    except MemoryError as error:
        raise ImageLoadError(
            "Not enough memory to decode this image. Close other images or "
            "applications and try again."
        ) from error
