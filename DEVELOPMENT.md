# A5ImageViewer Development Guide

This document is a technical handoff for developers and coding agents working on
A5ImageViewer. It describes the architecture, important implementation choices,
build and test workflow, and the behavioral contracts that are easy to break
when changing the application.

It includes the October 9, 2026 rename-reader coordination and timer-test fix,
September 27 folder-tree rollback, September 25 crop-saving,
selection-outline, and folder navigation buttons, and September 23 Alt navigation.
Read [README.md](README.md) first for the product goals and user
facing overview.

## 1. Product Direction

A5ImageViewer is a Windows-oriented image browser, fullscreen viewer, and
lightweight batch editor. Its primary design constraint is responsiveness and
stability while the machine is under heavy CPU, RAM, GPU, or VRAM load.

The practical priorities are:

- Avoid deliberate GPU-heavy image pipelines. Image decoding and editing use
  Qt image classes and Pillow.
- Keep runtime dependencies small. The only direct runtime dependencies are
  PyQt6 and Pillow.
- Favor fast, direct keyboard workflows over feature breadth.
- Keep large folders usable through bounded caches, background workers,
  prioritization, and incremental model updates.
- Prefer native Windows behavior for file operations and associations where it
  adds meaningful convenience.
- Keep the interface functional and compact. Dark is the default theme, with
  Medium Dark and Light alternatives.
- Do not add a database or persistent thumbnail index without a compelling
  reason. The current application scans the active folder and caches decoded
  thumbnails only in memory.

This is not intended to match the complete editing or cataloguing surface of
XnView, FastStone, Photoshop, or similar applications.

## 2. Technology and Execution Model

| Area | Implementation |
| --- | --- |
| Language | Python 3 |
| GUI | PyQt6 Widgets, Graphics View, Qt Multimedia |
| Image processing | Pillow and Qt `QImage`/`QPixmap` |
| Tests | Standard-library `unittest`, mostly offscreen Qt |
| Portable build | PyInstaller `--onefile` |
| Installed build | PyInstaller `--onedir`, packaged with Inno Setup |
| Windows integration | `ctypes` calls to Shell and User32 APIs |
| Persistent state | One JSON file beside the source tree or executable |

The application is a traditional single-process Qt application. GUI objects
and models live on the Qt main thread. Thumbnail decoding, folder previews,
crop/viewer prefetch, conversion, batch rename, batch transforms, and transfer
preflight checks use worker threads. Results return to the GUI through Qt
signals.

There is no plugin system, dependency injection framework, ORM, telemetry,
network service, or updater.

## 3. Running, Testing, and Building

### Run from source

The convenient Windows launcher creates/reuses `.venv`, installs runtime
requirements, and starts the application:

```powershell
.\run.bat
```

Equivalent commands:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

`main.py` creates the `QApplication`, selects Fusion style, applies the saved
theme, parses the first existing command-line path, and constructs
`MainWindow`. Passing an image opens its folder, selects the image, and opens
fullscreen. Passing a folder opens the browser at that folder.

### Run tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

The current suite contains 230 tests. Test modules set
`QT_QPA_PLATFORM=offscreen` where GUI construction is needed. Tests that write
configuration should redirect `utils.file_ops.CONFIG_FILE` to a temporary
directory and restore it during teardown. Never intentionally run a settings
test against the user's real `config.json`.

Useful focused commands:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_adjust_board -v
.venv\Scripts\python.exe -m unittest tests.test_main_window_batch_integration -v
.venv\Scripts\python.exe -m compileall -q main.py ui utils
```

### GitHub Actions

`.github/workflows/windows-tests.yml` runs the existing unittest suite on one
Windows runner with Python 3.13. Pushes to `main` and pull requests targeting
`main` trigger it, except when all changed files are `README.md` and/or
`DEVELOPMENT.md`. Feature-branch pushes are tested through their pull request
rather than a second push run. Changes to the bundled `CHANGELOG.md`, runtime
resources, tests, dependencies, and build scripts still trigger tests.

Routine runs install only `requirements.txt` (PyQt6 and Pillow), use offscreen
Qt for the unit tests, and cache pip downloads. The existing source startup
test explicitly exercises the Windows platform plugin in a child process.
The test step uses `runner.temp` for `TEMP`/`TMP` so Python and Qt see the same
path spelling instead of the runner's short `RUNNER~1` profile alias.
New runs cancel superseded runs for the same event and ref.

For a pre-release packaged check, open **Actions > Windows tests > Run
workflow**, select the source branch, and enable **Build the portable EXE and
run its existing startup check**. Tests must pass first. This option calls
`build-exe.bat` with `A5_BUILD_NO_PAUSE=1`, reusing its build environment helper,
sanitized DLL search, and `scripts/check_executable.py`. PyInstaller is installed
only for this option. The frozen startup check uses the Windows Qt platform
plugin; it does not inherit the unit-test step's offscreen setting.

This optional check validates a freshly built portable executable, not the
already uploaded release binaries or the installer. It does not upload artifacts,
create tags, publish releases, or change the existing local/Codex build process.
`build-installer.bat` continues to check its onedir executable locally. Release
and tag events do not start additional CI runs.

Because documentation-only changes skip the entire workflow, do not make this
workflow a required branch-protection check: GitHub can leave a skipped required
check pending and block a documentation-only pull request.

### Build executables

```powershell
.\build-exe.bat
.\build-installer.bat
```

Both scripts call `prepare-build-env.bat`, which creates/reuses the root
`.venv` and installs `requirements-build.txt` when PyQt6, Pillow, or
PyInstaller is missing.

`scripts/build_app.py` runs PyInstaller with a restricted Windows `PATH`:
Windows system directories and the selected Python installation. It clears
external Python/Qt import paths so tools such as Poppler cannot contribute an
incompatible `icuuc.dll` or other libraries. Qt's own DLLs are collected from
the environment's PyQt6 package. Do not run release builds with an unrestricted
developer-tool `PATH`.

Both build scripts run `scripts/check_executable.py` against the actual frozen
EXE before copying the portable release file or compiling the installer.
The internal `--self-test REPORT.json` command checks Qt imports, the Windows
platform plugin, browser rendering, PNG/JPEG decoding, and About resources.
It opens no visible windows and uses temporary configuration. A failure stops
the build and prints the captured traceback. To check an existing build:

```powershell
.venv\Scripts\python.exe scripts\check_executable.py output_exe\A5ImageViewer-Portable.exe
```

Build outputs go to `output_exe`:

- `build-exe.bat` creates the one-file portable `!A5ImageViewer.exe` and a
  byte-identical `A5ImageViewer-Portable.exe` release copy.
- `build-installer.bat` creates a PyInstaller onedir staging tree and compiles
  `A5ImageViewer-Setup.exe` with Inno Setup 6 or 7.

Both bundles include `LICENSE` and `CHANGELOG.md` for offline About content.
Release filenames remain stable. The release tag and `utils/app_info.py` date
identify dated updates; SHA256SUMS.txt is generated from the final binaries.

The local `PyToExe` folder is an ignored historical/local tool and is not used
by the supported build process.

For a release version change, keep these locations synchronized:

- `APP_VERSION` in `build-installer.bat`
- file and product versions in `installer/A5ImageViewer.version.txt`
- `APP_VERSION`, `RELEASE_DATE`, and `RELEASE_TAG` in `utils/app_info.py`
- the current entry in `CHANGELOG.md`
- the Git tag/release name

The Inno script receives `MyAppVersion` from the build BAT. The install folder
contains `A5ImageViewer.exe` and `_internal` directly. Upgrade installation
deletes/replaces those runtime files but deliberately preserves the generated
`config.json`.

## 4. Repository Map

- `ui/about_dialog.py`: Settings About button target and contextual F1 help,
  grouped shortcut reference, offline changelog, and full license. A WindowShortcut
  is registered separately on the browser, viewer, Crop, Adjust, and Settings.
  The Disable F1 checkbox immediately updates existing registrations and persists
  the preference for future windows. About itself does not save pending editor
  or Settings changes. Update shortcut descriptions when key bindings change.
- `utils/app_info.py`: app version/date, GitHub links, and bundled document paths.

### Entry point and coordination

- `main.py`: application creation, icon/theme setup, and command-line path
  activation.
- `ui/main_window.py`: central coordinator and largest module. Owns current
  folder/file state, navigation, menus, shortcuts, file operations, editor
  launches, worker services, and synchronization between views.

### Browsing and viewing

- `ui/thumbnail_view.py`: folder scanning, item model, thumbnail/folder-preview
  workers, in-memory cache, filtering, selection painting, and file drag source.
- `ui/image_viewer.py`: small reusable `QGraphicsView` pixmap viewer used for
  previewing and basic zoom/pan behavior.
- `ui/fullscreen_viewer.py`: fullscreen dialog, pixel selection, HUD,
  navigation, slideshow, shortcuts, and context menu.
- `ui/folder_shortcuts.py`: compact two-column system/favorites lists and the
  shrinkable drive-button strip.

### Editing and batch work

- `ui/crop_board.py`: serial crop/transform editor, selection handles, five
  entry undo history, save prompts, automatic `_crop` naming, and bounded
  adjacent-image prefetch.
- `ui/adjust_board.py`: serial Pillow-based adjustment and resize editor,
  bounded preview, zoom/pan, save/copy workflows, and setting carryover.
- `ui/batch_operations.py`: two-phase batch rename and atomic batch rotate/flip.
- `ui/convert_dialog.py`: threaded format conversion and optional transforms.

### Dialogs and file transfer

- `ui/dialogs.py`: split name/extension rename dialog and recent-folder
  Copy To/Move To destination dialog.
- `ui/transfer_conflicts.py`: asynchronous transfer preflight, comparison
  dialog, replace/skip/rename decisions, and queued job coordination.

### Shared behavior

- `ui/theme.py`: application palette, stylesheet, theme tokens, and generated
  scrollbar arrow assets.
- `ui/settings_dialog.py`: startup, theme, thumbnail size, and resource profile
  settings.
- `utils/file_ops.py`: JSON configuration plus Windows Shell copy/move/delete
  wrappers.
- `utils/windows_shell.py`: associated application/editor, print, wallpaper,
  and filtered Send To integration.
- `utils/image_ops.py`: older/simple Pillow helpers. Most current editor logic
  lives in the UI modules instead.

### Packaging and metadata

- `requirements.txt`: PyQt6 and Pillow.
- `requirements-build.txt`: runtime requirements plus PyInstaller.
- `installer/A5ImageViewer.iss`: Inno Setup layout and per-user file
  association registration.
- `installer/A5ImageViewer.version.txt`: Windows executable version resource.
- `A5ImageViewer.ico`: current application/build icon. `main.ico` is also
  present but current code and build scripts reference `A5ImageViewer.ico`.

## 5. Runtime Ownership and State Flow

`MainWindow` is intentionally the integration point. Avoid creating parallel
sources of truth in child widgets.

Important state fields include:

- `current_folder_path`: folder represented by the thumbnail model.
- `current_image_path`: current item path. Despite the name, context-menu code
  can temporarily point it at a folder, so always check `current_item_kind`.
- `current_item_kind`: `image`, `video`, `text`, or `folder`.
- `image_modified` and `modified_pixmap`: unsaved main/fullscreen rotate or
  flip state.
- `sort_key` and `sort_reverse`: active non-folder ordering.
- `show_images`, `show_pdfs`, `show_videos`, and `show_folders`: scan/filter
  categories.
- `navigation_history` and `navigation_index`: browser back/forward history.
  Address-row Back/Forward buttons use this same history. Their enabled states
  refresh when folders are remembered or history is traversed. Up opens the
  parent, including when the address editor has focus; Backspace still edits
  address text normally. Up is disabled at a drive root or with no folder open.
- `fullscreen_start_path`: path used to reconcile fullscreen exit and moves.

The thumbnail model uses a `QStandardItemModel`. Custom roles in
`ui/thumbnail_view.py` are the shared item contract:

| Role | Meaning |
| --- | --- |
| `PATH_ROLE` | Full path and primary item identity |
| `KIND_ROLE` | `image`, `video`, `text`, or `folder` |
| `EXT_ROLE` | Lowercase extension without a period |
| `SIZE_ROLE` | File size from `stat` |
| `MODIFIED_ROLE` | Modification timestamp |
| `WIDTH_ROLE` / `HEIGHT_ROLE` | Decoded image or video-frame dimensions |

The `ThumbnailView.files` worker record is a tuple of
`(path, name, extension, modified_time, kind, file_size)`. If model rows are
inserted, removed, or renamed manually, update `path_items`, cache keys, role
data, and worker records together. Prefer existing helpers such as
`add_thumbnail_paths`, `remove_thumbnail_paths`,
`update_saved_thumbnail_item`, `update_renamed_thumbnail_item`, and
`sync_worker_records`.

Path identity is normally compared using absolute, normalized,
case-normalized paths. Preserve this approach on Windows. Do not rely on the
slash style or original casing as identity.

## 6. Folder Scanning, Sorting, and Filtering

`ThumbnailView._scan_files` uses `os.scandir` and builds the model before image
decoding begins.

- Folders are always sorted A-Z and placed before files.
- Sort labels use Name/Date/Type with ↑/↓ for ascending/descending. The closed
  combo sizes to its contents; the popup includes extra space for its checkmark
  column so no label is elided. The filter is 50% wider than its previous
  natural width (previously capped at 170 logical pixels).
- Images/videos/PDFs use the selected name, date, or type ordering.
- The text filter applies to files; enabled folders remain visible for
  navigation. Whitespace-separated terms are ANDed as case-insensitive literal
  substrings of the filename (including its extension), in any order. Terms
  are split once per filter pass. Empty/whitespace-only input clears the text
  restriction. Existing row visibility, image navigation, and Show toggles
  continue to use the same filter; there is no separate search-results model.
- Changes in the Show popup are batched and applied after the menu closes.
- A favorite folder can remember its sort key/direction. Non-favorites do not
  write per-folder sort state.
- The main window title is the current directory name, or the drive name for a
  root, which helps distinguish multiple instances in the taskbar.
- Back/forward history supports Alt+Left, Alt+Right, and mouse thumb buttons.
- The address combo uses a 24-character minimum-content hint, independent of
  folder-history path lengths, and expands into available toolbar space.
  Back/Forward/Up use 16-pixel icons in 22-by-24 logical-pixel buttons with
  1-pixel gaps; the other toolbar icons retain their usual size.
- Alt+letter/top-row digit cycles to the next matching filename in the thumbnail
  model's current order, wrapping and skipping hidden rows. Shift+letter remains
  an alternative. Match `PATH_ROLE` basenames, never the display label (which
  includes resolution/type). `ShortcutOverride` and key presses are handled
  only on the thumbnail view/viewport, preserving plain-letter actions and text
  entry. Ctrl/AltGr, Meta, keypad Alt codes, and other Alt shortcuts are excluded.

The left navigation area combines fixed system locations, scrolling favorites,
a compact drive strip, and `QFileSystemModel` tree. The drive strip reports no
horizontal minimum and hides rightmost drive buttons when narrow. The tree uses
content-sized, per-pixel horizontal scrolling for deep paths, Qt's built-in icon
provider, and default row-height/column-sampling behavior.

The September 23 experiment with a Python cached icon/type provider, uniform row
heights, and visible-row column sizing was fully rolled back on September 27
after reports of intermittent freezes when navigating folders. A local native
Windows comparison (120 changes per provider, 24 folders of 96 JPEGs) did not
reproduce the reported hang, so the optimization remains a suspect rather than
a confirmed cause. The rollback restores the pre-experiment tree implementation;
it does not claim to resolve every source of filesystem latency. Do not reintroduce
the custom provider without investigating the reported regression. The crop
changes, address navigation buttons, and Alt filename navigation are independent
and remain in place.
Arrow expansion must not select the folder or trigger `load_current_folder`.

## 7. Thumbnail and Preview Pipeline

The thumbnail system is deliberately demand-aware:

1. A folder scan creates placeholder rows synchronously.
2. `ThumbnailTaskQueue` tracks background, priority, in-flight, awaiting-GUI,
   failed, and re-requested rows under a `Condition`.
3. Low-priority `ThumbnailWorker` threads decode scaled images with
   `QImageReader`.
4. Visible/nearby rows are promoted. Delivery is backpressured by
   `max_awaiting` so workers cannot flood the GUI event queue.
5. Results include a generation number. Stale results from an older folder or
   thumbnail size are ignored.
6. An `OrderedDict` cache tracks estimated byte cost and evicts old, unpinned
   entries when the configured limit is reached.

Visible rows are pinned against eviction. If the cache is full, background fill
pauses while requested/visible work can still proceed.

Folder mosaic previews use a separate delayed low-priority worker. It waits
about 1.2 seconds before background work, scans at most 2000 direct entries,
does not recurse, and uses at most four decodable images. Empty folders retain
the generic folder icon.

Video previews are owned by `VideoFrameGrabber` in `main_window.py` and use Qt
Multimedia (`QMediaPlayer`/`QVideoSink`) when available. Video rows display file
size immediately, before a frame is extracted. Requests are serialized and
generation checked. A missing multimedia backend should degrade to placeholder
icons, not prevent image browsing.

Reader lifetime is important on Windows. A live decoder can prevent rename,
move, or delete. Before destructive operations, use `pause_file_access`, clear
viewer prefetch, pause thumbnail background activity, and shut down the video
decoder when relevant. Resume through `resume_file_access` afterward.
These helpers do not drain in-flight readers, and background pause still allows
priority thumbnail requests. Single-file rename additionally uses
`ThumbnailView.set_file_access_paused`: it stops the existing work queues without
joining threads on the GUI, and prevents worker restarts until resumed. Current
reads finish naturally. Missing thumbnails resume from the existing cache;
normal folder navigation and editor background-pause behavior are unchanged.

## 8. Supported Content and Editing Boundary

The browser recognizes:

- Explicit images: JPG/JPEG, PNG, BMP, WebP, GIF, TIFF, and additional formats
  reported by `QImageReader`.
- PDF as a separate visible category. Internally it still has kind `image`, so
  code must also inspect `EXT_ROLE` or the extension.
- Videos: MP4, M4V, MOV, WebM, MKV, AVI, and WMV.
- Optional `.txt` caption files, case-insensitive, with `kind="text"`. The Show
  checkbox starts off each application session. Text rows have a TXT icon and
  file metadata, clear the image preview when selected, and open externally on
  activation. No text content is decoded, previewed, or prefetched. Mixed
  image/text selections use ordinary transfer, clipboard, drag, and conflict
  handling. Caption pairing is manual.

The fixed editable-image allowlist in `main_window.py` is JPG/JPEG, PNG, BMP,
WebP, GIF, and TIFF. PDFs are deliberately viewable but excluded from Crop and
Adjust navigation snapshots. Videos are preview-only.

Most Qt readers call `setAutoTransform(False)`. Do not silently enable EXIF
auto-rotation in one path without checking thumbnail, preview, fullscreen,
crop, save, and metadata behavior together.

## 9. Viewer and Fullscreen Behavior

`ImageViewer` is a `QGraphicsView` containing one `QGraphicsPixmapItem`. Setting
a pixmap updates the scene and fits it. Ctrl+wheel zooms; arrow keys pan.

`FullScreenViewer` is a shared image-view dialog owned by `MainWindow`, supporting
frameless fullscreen and a bordered, resizable window:

- Settings selects Fullscreen (default), Windowed, or Remember last used for
  opening the viewer. F11 and the context menu toggle the current mode.
- `show_viewer` and `apply_display_mode` centralize presentation. Loading another
  image or returning from editors must not force fullscreen or reset normal
  window geometry. Keep direct `showFullScreen` calls inside that implementation.
- Windowed mode initially maximizes on the browser monitor. Persist normal
  geometry, maximized state, monitor name, and last mode on mode switches/close;
  restore within an available screen if the original monitor disappears.
- `FullscreenImageViewer.zoom_mode` tracks Fit/manual zoom. Resize refits only in
  Fit mode; manual scale and image center are preserved. New images start in Fit.
- Title-bar close and Alt+F4 commit the displayed browser selection through the
  existing save prompt. Escape retains its original start-selection behavior;
  Enter commits the displayed selection. All close paths honor Cancel.

- Its current path must be updated on every navigation, rename, move, or save.
  Fullscreen file commands must act on this displayed path, not the path used
  when fullscreen was first entered.
- Navigation follows the current visible image order and stops at both ends.
- A successful move of the displayed image advances to the next remaining
  visible image, falls back to the previous image at the end, and closes
  fullscreen if none remain. Browser selection follows the replacement image.
  Queued moves choose the replacement at completion and compare normalized paths.
- Plain wheel navigates images; Ctrl+wheel zooms.
- Space also advances. Backspace and the Show in browser context-menu action
  synchronize browser selection/preview without closing or changing
  `fullscreen_start_path`. Preserve unsaved pixels during this explicit sync.
- The HUD belongs to the outer viewer dialog, positioned relative to
  the viewport. Do not parent it to the scrolling viewport: Qt scrolls child
  widgets along with its contents.
- The top-right sync button is removed. The context menu has explicit compact
  item padding to reduce the label/shortcut gap; next/previous list one primary
  shortcut each and keep the alternatives in visible tooltips. Key handling is
  unchanged.
- Right-drag pans. A right click without dragging opens the context menu.
- Left-drag creates a resizable pixel selection. Ctrl+A selects the whole
  image; Ctrl+C copies the selected pixels or whole image.
- Pixmap-changing actions clear the pixel selection.
- The HUD is a mouse-transparent label showing filename, format, and current
  displayed dimensions. Ctrl+H toggles/persists it; plain H remains horizontal
  flip.
- `5`/keypad 5 sets exactly 200 percent, `*` fits, `/` uses actual size, and
  `+`/`-` zoom.
- Ordered and randomized slideshows use a fixed 3000 ms timer. Pause toggles
  the saved mode. Slideshows stop rather than wrap.

Dialogs launched from fullscreen should be parented to the fullscreen dialog.
Use `transfer_dialog_parent`, `parent_override`, and the existing refocus
helpers so native/app dialogs do not disappear behind it.

## 10. Editing Workflows

### Main/fullscreen transforms

Single-image rotate/flip operations modify an in-memory `QPixmap` and set
`image_modified`. Preview and fullscreen share that displayed pixmap. Leaving
or changing the image invokes the save/discard/cancel prompt. A save refreshes
only the affected thumbnail.

Selecting multiple images routes rotate/flip to `BatchRotateDialog`. The worker
uses Pillow, writes a temporary file in the source folder, and calls
`os.replace` only after a successful encode. It preserves selected metadata
where supported, normalizes EXIF orientation to 1, and explicitly rejects
animated/multi-frame inputs.

### Crop Board

`CropBoard` loads a full `QPixmap` and supports crop, rotate, flip, reset, and a
five-state undo history. Selection rectangles become resizable immediately.
The shared `ResizableRectItem` paints one cosmetic outline on `rect()` and
always paints its eight handles. Do not call the base rect item's `paint()`:
Qt adds a second selection frame around `boundingRect()` (which includes the
handles), making the actual crop boundary ambiguous. Handles stay eight screen
pixels across zoom levels and remain interactive when the item is deselected.
Ctrl+A creates a resizable selection covering the entire current image.
Side buttons and +/=, -, *, / shortcuts provide zoom, Fit, and actual size.
Ctrl+wheel zooms and right-drag pans; left-drag retains crop selection. CropView
tracks Fit/manual zoom, refits on resize only in Fit, and resets to Fit on image
navigation or transforms. It uses the existing full-resolution pixmap and
prefetch cache; zoom never changes decoded pixels or selection coordinates.
Navigation uses a snapshot of visible editable image paths and does not wrap.

Unsaved navigation offers Save, Discard, and Cancel with session-only remember
behavior. Crop-to-file generates names in the destination folder:

```text
name_crop.ext
name_crop2.ext
name_crop3.ext
```

When Auto is off, a native folder picker starts at `crop_output_folder`, or the
current image's folder if unset, invalid, or unavailable. Generate the unique
name after the user chooses the destination, then remember that folder only
after a successful save. Auto always saves directly in `image_path`'s folder
and must not read or change the remembered manual destination. Both modes keep
the source extension. Cancellation or a failed save keeps the image/selection
and stored folder unchanged. The Ask checkbox controls overwrite confirmation
for saving back to the source.

Adjacent-image prefetch is bounded by the resource profile and a fixed 256 MiB
per-image cap in `_read_prefetch_image`. Header dimensions are checked before
decoding, and actual decoded cost is checked before caching. This shared worker
serves both Crop and viewer preloading. Larger images load on demand at full
resolution. Cache entries are checked against `(size, mtime_ns)` fingerprints
before reuse.

`utils/image_loading.py` implements the foreground decoding policy. The default
limit is 1024 MiB, independently configurable from 64 to 65536 MiB. The Qt
allocation limit and Pillow pixel guard are set on startup and when settings
are accepted. Foreground Qt and Adjust loaders check header dimensions at four
bytes per pixel before decoding; Qt also enforces its allocation limit for
higher-depth formats. A smaller `QT_IMAGEIO_MAXALLOC` override is reported
separately. No reduced-resolution foreground loading or GPU viewport is used.
Total process memory can exceed the setting because of display buffers, edits,
undo state, concurrent decodes, and cache entries.

Failed preview/viewer loads clear stale pixels and show an inline error, with
the required size and Settings hint for a size rejection. Other failures retain
the decoder error. Crop and Adjust show an Open Image warning; failed editor
navigation preserves the previous image. Readers release their Windows file
handles on failure as well as success.

`ImageViewer.paintEvent` selects smooth pixmap transformation only below 100%
logical zoom when `smooth_downscaling` is enabled. This applies to browser
preview and both viewer modes, including manual zoom and restored transforms.
It uses the existing CPU QWidget viewport and the original pixmap; at 100% or
above, or with smoothing disabled, fast unsmoothed rendering is retained.

### Adjust Board

`AdjustBoard` uses Pillow and keeps two sources:

- `original_pil`: full-resolution source used for final rendering.
- `preview_original_pil`: copy bounded to 1200 x 1200 for interactive updates.

The preview timer coalesces control changes at 40 ms. Manual preview zoom acts
only on the bounded preview, survives adjustment refreshes, and resets to Fit
when navigating to another image.

Available adjustments are brightness, contrast, gamma, exposure, sharpness,
temperature, tint, hue, saturation, RGB channels, shadows, highlights,
grayscale, invert, auto contrast, and equalize. Alpha is preserved where the
pipeline supports it.

Resize supports pixel/percent dimensions and Preserve Ratio, Stretch, Fit,
Fill/Crop, and Pad geometry. Padding has a color selector. Resampling options
are Automatic, Lanczos, sharper Lanczos, Bicubic, sharper Bicubic, Bilinear,
Hamming, Nearest, and Box. Automatic uses Lanczos for reduction and Bicubic for
enlargement; the sharper variants add a small unsharp mask.

Remember settings and Remember resize are intentionally separate. Adjustment
memory can persist in `config.json`; resize carryover is limited to the current
Adjust Board session. The selected resampling method is persistent.

O saves without closing or advancing, while Enter in numeric controls must not
save. Normal save offers overwrite, Save As, and `_adj` copy. Auto-name writes:

```text
name_adj.ext
name_adj2.ext
name_adj3.ext
```

Copy saves mark the current edit signature as saved but keep the original as
the navigation item. A copy added to the displayed folder is inserted into the
thumbnail model but not into the active Adjust Board navigation snapshot.

### Batch rename and convert

Batch rename templates use:

- `*` for the original basename.
- One contiguous `#` run for numbering and zero-padding.
- `\#` for a literal hash.

The rename worker first moves every source to a unique `.a5rename-*.tmp`, then
moves temporary files to final names. This supports swaps and case-only renames.
Windows sharing violations 32/33 are retried with bounded backoff. On failure,
the worker attempts rollback.

Batch Convert runs in a `QThread`, supports PNG/JPEG/WebP output, optional
rotate/flip, quality for JPEG/WebP, date preservation, and optional source
deletion. It is a simpler pipeline than batch rotate and does not use the same
atomic replacement helper. Treat changes to overwrite or deletion behavior as
high risk.

Conversion validates the complete output plan before writing: duplicate targets
and outputs that would overwrite another selected source are rejected. Source
deletion compares normalized paths and file identity so an in-place conversion
cannot delete its own output. Escape and window-close are blocked while the
conversion worker is running, and completion waits for the worker to exit.

## 11. File Operations and Conflict Handling

Single-file rename executes its filesystem callback in a dialog-owned QThread
before the Rename dialog accepts. Callbacks must not access GUI objects. The
dialog's start/finish signals coordinate readers on the GUI thread. A successful
rename updates browser/viewer paths before readers resume; failure/cancellation
restores the prior pause state. `rename_with_sharing_retry` handles only Windows
errors 32/33, with a ten-second retry deadline and cancellation between attempts.
Do not call its sleep/backoff loop from the GUI thread.
A destination collision or filesystem error leaves the dialog open with an
inline message and the attempted name selected for correction. Only successful
renames update the thumbnail model. Cancel, Escape, and the close button request
interruption and keep the worker owned until its finished signal arrives. If a
rename already succeeded before cancellation, success wins so the displayed paths
still match disk. Otherwise cancellation preserves the original path.

There are two related transfer paths:

1. Copy To/Move To dialogs call `TransferCoordinator`. Preflight checks happen
   in up to two daemon threads so a slow disk or network share does not block
   image navigation. Plans are resolved in queue order. Conflicts open one
   application-modal comparison dialog with source/destination previews and
   Replace, Skip, Rename, and corresponding All actions. Suggested names use
   `name-ren(1).ext`, incrementing existing suffixes without enumerating the
   entire destination directory.
2. Clipboard paste, drag/drop, and direct Send To folder actions currently use
   `transfer_files_to_folder`, which submits the paths together through the
   native Shell operation. When dropping onto a tree or folder-thumbnail
   target, same-drive drops default to move, cross-drive drops default to copy,
   Ctrl forces copy, and Shift forces move. A drop onto thumbnail-view empty
   space is the existing copy-into-current-folder path.

Exact transfer plans are split into non-overwrite and overwrite groups and sent
through `SHFileOperationW` with double-null-terminated source/destination lists.
Cancellation is represented as `None`, failure as `False`, and completion as
`True`. Keep this distinction: a user cancellation must not produce a failure
popup.

File operations check the filesystem after Shell completion to determine which
sources actually moved or copied. Successful local changes update thumbnail
rows incrementally; avoid rescanning a large directory unless model state cannot
be reconciled.

Delete uses a custom confirmation followed by `SHFileOperationW`. Normal delete
sets `FOF_ALLOWUNDO` for the Recycle Bin; Shift+Delete is permanent. Copy, move,
delete, and rename retry sharing violations with short bounded backoff to
allow Qt/Pillow readers to release handles.

Thumbnail deletion includes selected folders through
`selected_file_paths(include_folders=True)`; confirmation explicitly includes
their contents. Other callers retain the existing file-only default.

Clipboard interoperability uses file URLs plus Windows `Preferred DropEffect`
and a private `application/x-a5imageviewer-cut` marker. It supports files and
folders. Fullscreen Copy to Clipboard is separate and copies pixels.

## 12. Windows Integration

`utils/windows_shell.py` keeps optional Shell behavior isolated:

- `ShellExecuteW` with `open`, `edit`, and `print` verbs.
- `SystemParametersInfoW` for desktop wallpaper.
- `SHGetKnownFolderPath(FOLDERID_SendTo)` for the current user's Send To folder.
- `subprocess.list2cmdline` for safely quoting multiple paths passed to Send To
  application targets.

Send To enumeration deliberately supports ordinary folders plus `.lnk`, `.exe`,
`.com`, `.bat`, and `.cmd` entries. COM-backed Shell handlers such as compressed
ZIP, mail recipient, and desktop shortcuts are excluded. The command line is
rejected above 30,000 characters.

On non-Windows platforms, associated-program opening falls back to
`QDesktopServices`; editor, print, wallpaper, Send To, and the core
`SHFileOperationW` file-management path are Windows-specific. Cross-platform
support is best-effort, not a current release guarantee.

The installer registers a per-user ProgID and SupportedTypes for JPG/JPEG, PNG,
BMP, WebP, GIF, and TIFF. Windows still controls the final default-app choice;
the optional installer task opens the relevant Settings page.

## 13. Configuration Model

`utils/file_ops.py` owns the single `config.json`.

- Source run: workspace root beside `main.py`.
- Frozen onefile/onedir run: beside `sys.executable`.
- The install/portable directory must therefore be writable for persistence.
- Legacy slash styles are normalized on read; new recent/address/last-folder
  writes use native normalized absolute paths.
- File handles are scoped to individual reads/writes, with no lifetime lock or
  cached whole-config snapshot. Sequential changes by separate processes read
  the latest file and retain unrelated settings. Simultaneous read/modify/write
  operations are not serialized and may overwrite each other.

`utils/application_launch.py` starts independent processes with
`QProcess.startDetached`. The toolbar's app-icon-only New instance action,
separated from adjacent controls, (Ctrl+Shift+N) opens
the current folder; folder menus in quick access, favorites, the directory tree,
and thumbnails pass their clicked folder. Frozen builds launch `sys.executable`
with `PYINSTALLER_RESET_ENVIRONMENT=1` in the child's environment, so one-file
builds extract their own resources and survive the original process closing.
Source runs launch the same Python environment (`pythonw.exe` on Windows when
available) with the absolute `main.py` path. Paths are separate arguments,
standard streams are detached, and launch failures produce a warning. Taskbar
integration is unchanged.

Important keys and defaults:

| Key | Default / purpose |
| --- | --- |
| `recent_folders` | `[]`; Copy To/Move To history |
| `address_folders` | `[]`; address bar history, capped at 20 |
| `last_folder` | empty; startup restoration |
| `favorite_folders` | ordered full paths |
| `favorite_display_names` | normalized path to alias map |
| `favorite_sort_settings` | favorite path to name/date/type order |
| `startup_behavior` | `last_used`; alternative `empty` |
| `thumbnail_size` | `200` pixels |
| `ui_theme` | `dark`; also `medium_dark`, `light` |
| `resource_profile` | `balanced`; also conservative/performance/custom |
| `custom_thumbnail_workers` | `4`, clamped 1..8 |
| `custom_thumbnail_cache_mb` | `2048`, clamped 256..5120 |
| `custom_crop_prefetch_mb` | `512`, clamped 128..1024 |
| `max_decoded_image_mb` | `1024`; integer 64..65536, invalid values use default |
| `smooth_downscaling` | `true`; CPU smoothing below 100% in preview/viewer |
| `disable_f1_shortcut` | `false`; About remains accessible from Settings |
| `fullscreen_hud_visible` | `true` |
| `viewer_default_mode` | `fullscreen`; also `windowed` or `last_used` |
| `viewer_state` | validated last mode, normal geometry, maximized state, window monitor, and last viewer monitor |
| `slideshow_mode` | `ordered`; alternative `random` |
| `quality_jpeg`, `quality_webp` | `90` |
| `convert_appendix` | `_result` |
| `crop_ask_overwrite` | `true` |
| `crop_auto_name_copies` | `false` |
| `crop_output_folder` | Last successful manual crop destination; unset initially |
| `remember_adjustments` | `false` |
| `adjustment_values` | persisted only when adjustment memory is enabled |
| `adjust_auto_name_copies` | `false` |
| `adjust_resampling` | `auto` |

Resource presets request 2/4/8 thumbnail workers and 512/2048/5120 MiB caches,
but effective workers are capped at `max(1, logical_cpu_count - 2)`. Crop
prefetch uses one or two workers and 256/512/1024 MiB in the presets.

The current configuration implementation is intentionally simple: each setter
loads the whole JSON object, changes one field, and writes the whole file. There
is no process lock, merge, temporary-file write, or atomic replace. Multiple app
instances can all write it; the last writer can lose a recent update from
another instance. A write interruption or truly overlapping write is also a
possible corruption risk. `load_config` catches parse errors and returns a
minimal default, so a subsequent write after corruption can replace old state.

This is acceptable for the small, non-critical settings file under the current
single-user usage pattern. If configuration durability is hardened later, use
same-directory temporary write, flush/fsync where appropriate, and
`os.replace`, then consider a small inter-process lock or merge strategy. Keep
the public getter/setter API stable so UI modules do not learn the storage
details.

Session-only choices must remain non-persistent unless intentionally changed:

- main edit prompt auto-save choice
- Crop Board navigation save/discard choice
- Adjust Board navigation save/discard choice
- Convert overwrite-warning suppression
- Adjust Board Remember resize state

## 14. Themes and UI Conventions

Theme behavior is centralized in `ui/theme.py`. `apply_theme` changes the
application palette and stylesheet in place; it must not rebuild models, flush
thumbnail caches, decode images, or change selection.

Theme tokens cover surfaces, text, disabled state, selection, controls, focus,
checkboxes, scrollbars, splitters, and thumbnail borders. Scrollbar arrows are
small recolored standard Qt icons written to a process-local `QTemporaryDir`.

Image canvases remain explicitly dark in every theme, and fullscreen remains
black. Keep canvas selectors scoped so they do not force menus and dialogs dark
under the Light theme.

UI conventions established in the project:

- Compact controls and stable dimensions are preferred.
- Use existing Qt standard icons or the established local icon generators.
- Context menus expose keyboard shortcuts near the action.
- Buttons that create files repeatedly should give visible pressed feedback.
- Important dialogs use mnemonic ampersands and explicit single-key handling
  where focus behavior could otherwise be ambiguous.
- Do not make Enter save from Adjust Board numeric fields.
- Keep selection borders clear of thumbnail filename text.
- Keep system folders visible while favorites scroll in two columns.
- Theme app-owned dialogs; native Windows dialogs retain OS appearance.

## 15. Concurrency and Performance Invariants

These are the most important engineering constraints for future changes:

1. Never mutate Qt widgets or models from a worker thread. Emit data and apply
   it on the GUI thread.
2. Every reusable asynchronous result needs a generation and/or file
   fingerprint check. Folder changes, renames, saves, and thumbnail-size changes
   can otherwise display stale content.
3. Decode at the requested size when possible. Do not routinely decode full
   images only to make thumbnails.
4. Bound memory by byte cost, not only item count.
5. Prioritize visible and adjacent content. Background completion is secondary
   to interaction latency.
6. Keep worker delivery backpressured. An unbounded signal queue can freeze the
   UI even when decoding itself is threaded.
7. Stop/pause readers before operations that require Windows to rename, move,
   delete, or replace files.
8. Prefer incremental thumbnail updates after a local operation. Full rescans
   are expensive and disturb selection/scroll state.
9. Preserve model order when collecting multi-selection paths. It defines batch
   numbering, serial editor order, and Send To argument order.
10. Navigation at the first/last item stops. Do not reintroduce wrapping unless
    a separate explicit mode is designed.
11. Keep conflict preflight asynchronous and avoid enumerating an entire large
    destination folder merely to find one free rename.
12. Parent modal dialogs to fullscreen when fullscreen is active, and restore
    focus afterward.

## 16. Test Organization

| Test module | Primary coverage |
| --- | --- |
| `test_adjust_board.py` | effects, resize geometry/resampling, serial navigation, save naming, zoom |
| `test_adjustment_settings.py` | persisted/clamped adjustment settings |
| `test_appearance.py` | themes, favorites layout, repaint without reload |
| `test_batch_operations.py` | rename parser/plans/rollback and atomic transforms |
| `test_config_paths.py` | path normalization and frozen/source config location |
| `test_convert_dialog.py` | conversion collisions, source deletion, and dialog worker lifetime |
| `test_crop_transforms.py` | crop selection, transforms, prompts, shortcuts, naming |
| `test_selection_outline.py` | one actual selection edge and always-visible handles at Fit/manual scales |
| `test_delete_files.py` | Shell operation batching, cancellation, sharing retries |
| `test_dialogs.py` | split rename fields and Windows filename validation |
| `test_rename_readers.py` | real Windows decoder locks, responsive rename retries, cancellation, reader resumption, viewer paths, and late-cancel success |
| `test_favorites.py` | aliases and favorite-specific sort persistence |
| `test_folder_previews.py` | delayed non-recursive mosaics and stale cancellation |
| `test_fullscreen_hud.py` | HUD, pixel selection, zoom, focus, slideshow, shortcuts |
| `test_fullscreen_moves.py` | queued moves, normalized paths, next-image selection, cancellation, and empty-folder exit |
| `test_image_loading.py` | decoding limits/settings, Qt/Pillow loading, error recovery, reader release, large-image prefetch exclusion, CPU smoothing across zoom levels |
| `test_new_instance.py` | launch paths/errors, detached process lifetime, sequential shared config access, toolbar/folder commands, compact viewer menu and removed sync button |
| `test_about_dialog.py` | offline content, contextual F1, disabling/re-enabling F1, Settings access, and unchanged pending preferences |
| `test_viewer_modes.py` | mode/settings persistence, geometry fallback, F11, resizing/zoom, and close cancellation |
| `test_viewer_workflows.py` | folder deletion, browser synchronization, Space, fixed HUD, crop zoom/pan and cached navigation |
| `test_text_files.py` | TXT filtering, external opening, mixed transfers/clipboard, conflicts, and incremental updates |
| `test_main_window_batch_integration.py` | model synchronization and cross-component workflows |
| `test_reader_lifetimes.py` | Windows file-handle release behavior |
| `test_save_prompt.py` | main edit save/discard session behavior |
| `test_startup_activation.py` | command-line file/folder activation and titles |
| `test_browser_navigation.py` | folder switching with active thumbnail/preview decoders, arrow versus folder selection, Alt filename/digit cycling, filters, wrapping, shortcut/text-entry isolation, and address navigation buttons |
| `test_thumbnail_filtering.py` | type filters, PDF boundary, video labels |
| `test_transfer_conflicts.py` | async preflight and conflict choices/naming |
| `test_windows_shell.py` | Shell verbs, Send To, print, wallpaper, platform guards |

For a bug fix, add a focused regression close to the owning module. For changes
touching `MainWindow`, file identity, selection, worker lifetime, or save/move
behavior, also run the complete suite.

No automated visual snapshot suite exists. For layout/theme changes, supplement
unit tests with manual checks at common Windows display scales and with Dark,
Medium Dark, and Light themes.

## 17. Safe Change Recipes

### Add a new persisted setting

1. Add validated getter/setter functions in `utils/file_ops.py` with a safe
   default for missing/invalid data.
2. Keep old config files readable without migration when possible.
3. Bind the UI in its owning dialog/module.
4. Test default, invalid fallback, persistence, and any live application effect.

### Add a new thumbnail-visible file type

1. Decide whether it is `image`, `video`, `folder`, or needs a new kind.
2. Update scanning, filter categories, placeholder icon, labels, status data,
   context menu guards, and editable snapshots.
3. Confirm the decoder releases file handles.
4. Test visibility independently from existing categories.

### Add an image-changing operation

1. Decide whether it is in-memory single-image, serial editor, or batch work.
2. Route all displayed pixmap changes through the existing viewer helpers so
   fullscreen HUD/selection state stays correct.
3. Mark or baseline dirty state correctly.
4. Pause competing readers before overwriting.
5. Refresh only affected thumbnails and reconcile date sorting if mtime changes.
6. Test preview, fullscreen, navigation prompt, failed save, and alpha/metadata
   behavior where relevant.

### Add a background worker

1. Define who owns shutdown and connect it to application teardown.
2. Add cancellation and stale-result rejection before adding concurrency.
3. Bound task admission and memory.
4. Use low priority for speculative/background work.
5. Add a test that changes folder/generation while a result is in flight.

### Change file transfer behavior

1. Preserve multi-selection model order.
2. Distinguish cancel from failure.
3. Release readers before moving/replacing/deleting.
4. Keep preflight off the GUI thread and dialogs on it.
5. Verify local disk, missing source/destination, conflicts, rename numbering,
   fullscreen current-path handling, and partial success.

## 18. Known Constraints and Maintenance Notes

- `ui/main_window.py` is over 3000 lines and is the main architectural pressure
  point. Extract only cohesive services with clear ownership; broad rewrites
  risk breaking tightly coordinated selection and fullscreen behavior.
- Configuration writes are not atomic and are not locked across instances.
- Core file copy/move/delete uses the legacy `SHFileOperationW` API rather than
  full COM `IFileOperation` integration.
- Send To intentionally omits COM Shell handlers.
- The application has no persistent thumbnail database; reopening a folder can
  require decoding again.
- PDF support depends on what the Qt image stack can decode and is view-only.
- Video support depends on the installed Qt Multimedia/platform codecs.
- Animated/multi-frame editing is limited; batch transform refuses it, while
  simpler editor paths may flatten to a single frame.
- Metadata preservation differs between save paths. Batch rotate is the most
  deliberate; QPixmap saves and Adjust/Crop/Convert do not promise complete
  metadata round-tripping.
- The portable and installer executables are unsigned, so SmartScreen warnings
  are expected.
- Error reporting is mostly modal dialogs plus a few `print` calls. There is no
  structured logging system.
- `utils/image_ops.py` overlaps some newer UI-owned editing logic and should not
  automatically be treated as the canonical path for new features.

## 19. Developer/Agent Completion Checklist

Before considering a change complete:

- Read the affected module and its tests before editing.
- Preserve unrelated workspace changes.
- Check ownership of current path, selection, model roles, and fullscreen state.
- Check whether a worker or decoder still holds the target file.
- Keep Windows-only calls isolated and provide a deliberate non-Windows result.
- Add focused regression coverage.
- Run `py_compile` for changed Python modules.
- Run the focused test module, then the full suite for cross-component changes.
- For UI changes, inspect all three themes and a narrow/wide layout.
- For image changes, verify preview, fullscreen, save failure, and thumbnail
  refresh behavior.
- For build/release changes, verify both BAT files, installer staging, output
  paths, version metadata, and config preservation.

The best default is a small, tested change that follows an existing ownership
boundary. Responsiveness and predictable file behavior matter more here than a
larger abstraction or a longer feature list.
