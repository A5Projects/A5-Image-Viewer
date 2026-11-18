"""Write PNG generation data for ComfyUI and the local prompt extractor."""

import json
import os
import re
import tempfile

from PIL import Image

from utils.compact_metadata import compact_png_summary


GRAPH_TAGS = {"prompt": 0x0110, "workflow": 0x010F}


def _invalid_json_constant(value):
    raise ValueError(f"{value} is not a JSON number")


def _graph_tag(key, text):
    try:
        json.loads(text, parse_constant=_invalid_json_constant)
    except ValueError as error:
        raise ValueError(f"The PNG's {key} field contains invalid JSON.") from error
    # TIFF ASCII fields lose literal Unicode. Escape only those characters to
    # preserve custom nodes, large seed values and numeric literals verbatim.
    ascii_json = re.sub(r"[^\x00-\x7f]+", lambda m: json.dumps(m[0])[1:-1], text)
    return f"{key}:{ascii_json}"


def webp_metadata(opened):
    fields = opened.text if opened.format == "PNG" else {}
    exif = opened.getexif()
    # A mixed selection may include already tagged WebPs. Verify their original
    # prompt fields too, even if no new PNG text fields need to be translated.
    tags = {tag: exif[tag] for tag in (0x010E, 0x010F, 0x0110, 0x9286) if tag in exif}
    for key, tag in GRAPH_TAGS.items():
        if key in fields:
            tags[tag] = _graph_tag(key, fields[key])
    summary = compact_png_summary(fields, opened.size) if fields else None
    options = {}
    if summary is not None:
        # The standalone extractor reads its compact JSON from the WebP XMP chunk.
        xmp = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        options["xmp"] = xmp
        if 0x010E not in exif:
            tags[0x010E] = json.dumps(summary, ensure_ascii=True, separators=(",", ":"))
        if 0x9286 not in exif:
            tags[0x9286] = b"UTF8\0\0\0" + xmp
    else:
        xmp = opened.info.get("xmp") or fields.get("XML:com.adobe.xmp")
        if xmp:
            options["xmp"] = xmp.encode("utf-8") if isinstance(xmp, str) else xmp
    for tag, value in tags.items():
        exif[tag] = value
    if exif:
        options["exif"] = exif.tobytes()
    if opened.info.get("icc_profile"):
        options["icc_profile"] = opened.info["icc_profile"]
    return options, tags


def save_verified_webp(image, target, quality, options, tags, verify_pixels=False):
    """Publish only after the temporary WebP returns the expected metadata."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=os.path.dirname(os.path.abspath(target)), prefix=".a5-webp-",
            suffix=".webp", delete=False,
        ) as temp:
            temp_path = temp.name
            image.save(temp, "WEBP", quality=quality, **options)
        with Image.open(temp_path) as result:
            if result.format != "WEBP" or result.size != image.size:
                raise ValueError("The saved WebP has unexpected image dimensions or format.")
            exif = result.getexif()
            if any(exif.get(tag) != value for tag, value in tags.items()):
                raise ValueError("The saved WebP did not retain its generation metadata.")
            if "xmp" in options and result.info.get("xmp") != options["xmp"]:
                raise ValueError("The saved WebP did not retain its compact prompt summary.")
            if verify_pixels:
                result.load()
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            os.remove(temp_path)
