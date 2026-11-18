"""Encode a complete animation and verify playback before the caller publishes it."""

from hashlib import sha256

from PIL import Image

from utils.file_ops import get_image_settings
from utils.image_loading import MIB, check_image_size


def _webp_loop(source):
    if source.format == "WEBP":
        return source.info["loop"]
    # A GIF extension counts repetitions after the initial play. WebP counts plays.
    repeat = source.info.get("loop")
    if repeat is None:
        return 1
    if repeat == 65535:
        raise ValueError("The GIF repeat count exceeds WebP's limit of 65,535 plays.")
    return repeat + 1 if repeat else 0


def _alpha_digest(frame):
    alpha = frame.getchannel("A")
    if alpha.getextrema() == (255, 255):
        return None
    return sha256(alpha.tobytes()).digest()


def save_animated_webp(source, destination, quality, transform=None, *, limit_mb=None):
    if limit_mb is None:
        limit_mb = get_image_settings()["max_decoded_image_mb"]
    check_image_size(*source.size, limit_mb)
    loop = _webp_loop(source)
    options = {key: source.info[key] for key in ("icc_profile", "exif", "xmp") if key in source.info}
    options["background"] = source.info["background"] if source.format == "WEBP" else (0, 0, 0, 0)

    frame_count = source.n_frames
    if transform is not None:
        # Pillow's append_images keeps transformed frames in memory. With no
        # transform, its encoder can pull each frame directly from the source.
        if source.width * source.height * 4 * frame_count > limit_mb * MIB:
            raise ValueError(
                f"Rotating or flipping this animation exceeds the {limit_mb:,} MiB decoded-image "
                "limit. Choose no rotation or raise Maximum decoded image size in Settings."
            )

    durations = []
    alphas = []
    transformed = []
    canvas_size = source.size
    for index in range(frame_count):
        source.seek(index)
        check_image_size(*source.size, limit_mb)
        if source.size != canvas_size:
            raise ValueError(f"Frame {index + 1} exceeds the original animation canvas.")
        frame = source.convert("RGBA")  # Resolve the source palette and frame disposal.
        durations.append(source.info.get("duration", 0))
        if transform is not None:
            frame = transform(frame)
            transformed.append(frame)
        alphas.append(_alpha_digest(frame))
    del frame

    source.seek(0)
    first = transformed[0] if transformed else source
    first.save(destination, "WEBP", save_all=True, append_images=transformed[1:],
               duration=durations, loop=loop, quality=quality, **options)
    size = first.size
    transformed.clear()
    del first

    with Image.open(destination) as output:
        if (output.format != "WEBP" or output.size != size or output.n_frames != frame_count
                or output.info.get("loop") != loop):
            raise ValueError("The WebP encoder did not preserve the animation's frames, size or loop count.")
        for index, duration in enumerate(durations):
            output.seek(index)
            decoded = output.convert("RGBA")
            if output.info.get("duration") != duration or _alpha_digest(decoded) != alphas[index]:
                raise ValueError(f"The WebP encoder changed timing or transparency on frame {index + 1}.")
