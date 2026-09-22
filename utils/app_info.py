from pathlib import Path

APP_NAME = "A5 Image Viewer"
APP_VERSION = "1.0.0"
RELEASE_DATE = "2026-09-22"
RELEASE_TAG = "v1.0.0-20260922.1"
GITHUB_URL = "https://github.com/A5Projects/A5-Image-Viewer"


def bundled_file(name):
    # PyInstaller preserves this module's location relative to bundled data.
    return Path(__file__).resolve().parent.parent / name


def read_bundled_text(name):
    try:
        return bundled_file(name).read_text(encoding="utf-8")
    except OSError:
        return f"{name} is unavailable in this build. See {GITHUB_URL}."
