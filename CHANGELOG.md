# Changelog

## 2026-11-18 — v1.0.0-20261118

- Reopening a folder reuses unchanged thumbnails from a bounded RAM cache.
  The cache is cleared when A5 closes and creates no thumbnail database on disk.
  Image thumbnails and folder previews share worker and memory limits when
  switching folders. The grid also updates faster after bulk file operations.
- Batch Convert can keep the full ComfyUI workflow, API prompt and compact
  prompt/settings summary when converting still PNGs to WebP. A5 verifies
  the metadata before replacing the destination.
- Batch Convert preserves frame timing and looping when converting animated
  GIFs and WebPs to animated WebP. Optional GIF playback animates visible
  thumbnails and the selected preview, or just the preview. Playback starts off.
  Video previews also start off and release the player when disabled.
- Image Adjust asks before closing with unsaved changes, with a choice to
  remember the action for the session. Adjusted PNGs retain their text metadata.
  Resize to Fill uses less working memory, and Adjust exports, Batch Convert
  and Rotate honor the configured decoded-image limit.
- The visited-folder history and shared Copy To / Move To history now have
  separate limits. Both default to 30 and can be set from 1 to 10,000.
  A5 checks offline history entries when opened. Filtering restricts file
  operations to visible selected items.

## 2026-10-20 — v1.0.0-20261020

- Added signed-angle rotation to Image Adjust's bottom row and Crop Board's
  toolbar/context menu. Normal save controls apply; Reset restores orientation,
  and Crop Undo also restores the previous crop box.
- Image Adjust's rotation uses an absolute angle from the original orientation.
  Rotate or Enter applies it; applying 0° keeps all other adjustments intact.
- Left double-click closes fullscreen/windowed viewing like Enter, selecting the
  displayed image in the browser and honoring save/discard/cancel.
- About now offers a manual Check for updates button with an inline result.
  It contacts GitHub only on a click, never automatically, and installs nothing.
- Widened Crop Board's aspect-ratio dropdown so every option remains readable.

- Single-file rename now suspends new thumbnail reads and retries temporary
  Windows sharing violations in a worker thread. The dialog stays responsive,
  supports cancellation while waiting, and preserves editable collision errors.
- Stabilized the Crop Board button-feedback test by waiting for the expected
  state with a timeout instead of assuming a timer fires within 170 ms.

- The address field now shrinks independently of long folder-history entries.
  Smaller, closely spaced Back/Forward/Up buttons leave more toolbar controls
  visible in narrow windows.
- Reverted the experimental folder-tree icon provider and layout optimizations
  after reports of intermittent freezes when changing folders. The original Qt
  tree behavior is restored; the cause of the reported freezes is unconfirmed.

- Crop to File with Auto off now chooses a folder and remembers the last
  successful manual destination across restarts. Auto saves beside the current
  image. Both number existing `_crop` filenames in the chosen destination;
  tooltips explain the difference.
- Crop Board and fullscreen/windowed pixel selections now show one outline
  at the actual selection boundary, with resize handles always visible.
- Added compact Back, Forward, and Up buttons beside the browser address field,
  using the existing folder navigation and keyboard shortcuts.

- Added Alt+letter and Alt+0–9 filename navigation in the thumbnail browser.
  Repeated presses cycle through visible matches in display order and wrap.
  Existing single-letter actions are preserved.
- Fixed the Shift+letter alternative to match actual filenames instead of
  resolution/type labels, and documented both options in About and the README.

## 2026-09-22 — v1.0.0-20260922.1

- Fixed the packaged application failing at startup with a QtWidgets DLL error.
  Builds now exclude unrelated tools from their DLL search path, preventing an
  incompatible ICU library from replacing the Windows dependency used by Qt.
- Both build scripts now run the generated application through a startup check
  before producing release files. It checks the native Windows Qt plugin,
  browser rendering, PNG/JPEG decoding, and bundled About documents using
  temporary configuration.

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
