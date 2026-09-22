# Changelog

## 2026-09-22 — v1.0.0-20260922

- Added About and F1 help with shortcuts grouped by window, the GPLv3 license,
  GitHub links, and an offline changelog.
- Added a remembered Disable F1 shortcut checkbox in About; Settings access
  remains available.
- Added a configurable decoded-image size limit (default 1024 MiB), clear load
  errors, and a 256 MiB per-image preloading cap for large images.
- Added optional CPU-only smooth downscaling below 100% zoom, preserving full
  resolution and unsmoothed viewing at 100% and above.
- Added AND filename filtering: all space-separated terms must match.
- Added independent instances from the toolbar, Ctrl+Shift+N, and folder menus.
- Made sorting controls more compact, widened the filter, and simplified the
  New instance button and viewer context menu.
- Removed the viewer's top-right Show in browser button; the context-menu
  command and Backspace shortcut remain.
- Portable and installer downloads now use stable filenames:
  `A5ImageViewer-Portable.exe` and `A5ImageViewer-Setup.exe`.

## 2026-09-18 — v1.0.0-20260918

- Crop Board zoom with +/−, Ctrl+mouse wheel, Fit, actual size, and right-drag pan.
- Windowed image viewing with F11 switching, remembered geometry and monitor,
  and a default-mode setting.
- Show in browser / Backspace selects the viewed image in the thumbnail browser;
  Space advances to the next image.
- Optional TXT caption-file browsing for copy/move and clipboard operations.
- Folder deletion from the thumbnail browser, with confirmation.
- Viewer navigation, file-transfer, and conversion workflow fixes.
- Expanded regression coverage, user documentation, and development guide.

## 2026-09-10 — v1.0.0

First packaged release:

- Windows installer with optional file-association integration.
- Portable single-file executable.
- No local Python installation required.
- Source code available under GPLv3.
