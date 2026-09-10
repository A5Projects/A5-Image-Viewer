# A5 Image Viewer

A fast, Windows-oriented image browser, fullscreen viewer, and lightweight
editor written in Python with PyQt6 and Pillow.

## Design priorities

The leading directive was not a vast number of features, but stability and
responsiveness, even under heavy system, GPU, and VRAM load from local AI or
games. My previous favorite viewer was freezing and crashing. The features grew
nonetheless into a personal best-of, but only under that guiding rule.

- Very low or no VRAM use was paramount throughout. It works quickly and
  flawlessly for me even while ComfyUI uses 100% of the VRAM and 50% of RAM.
- The minimum necessary dependencies, for size and stability. When in doubt,
  fancy feature ideas were dropped, such as more image-adjustment options.
- A functional UI with three themes: Dark, Medium Dark, and Light.
- The UI, shortcuts, and choice of available features are very much my personal
  best-of, focused on fast, one-button workflows.
- Adjustable CPU and RAM use for thumbnail mode, without going overboard on
  settings.
- Basic file-manager options: rename, create a folder, and open in Explorer.
- Fast copying options: Copy To, Move To, remembered paths, visual conflict and
  renaming dialogs, automatic renaming, clipboard operations, and drag and drop.
- Single-key shortcuts, shown in the context menus.
- A fast and efficient Crop Board for cropping many images quickly. Its internal
  behavior and UI are very much based on my priorities.
- CPU-based image adjustments for size and appearance, with a simple functional
  UI and conveniences such as preserving settings between images.
- Batch conversion and batch renaming of images.
- Optional automatic naming and numbering for Crop Board and Image Adjust.

Because I use Windows, it was the priority. No precautions were taken to make
the application Linux-compatible despite its Python base, although making most
features work there should not be an enormous job.

## Quick start (Windows)

Download the current files from the
[latest GitHub release](https://github.com/A5Projects/A5-Image-Viewer/releases/latest):

1. Use `A5ImageViewer-Portable-1.0.0.exe` as a completely portable version with
   no installation or system changes. It creates `config.json` beside the EXE
   for settings and folder history, but creates nothing else.
2. Use `A5ImageViewer-Setup-1.0.0.exe` for a classic installer with optional
   Windows application and file-association integration.
3. To run from source, use `run.bat`. It creates the Python environment and
   installs dependencies on its first run, then starts the application. This
   requires Python 3 on `PATH`.

The executable builds are current as of the tagged release. They can also be
built locally using the instructions below.

## Screenshots

The interface should be familiar to anyone who has used an image viewer. Check
the context menus for the available shortcuts.

<img width="930" height="640" alt="A5 Image Viewer main window" src="https://github.com/user-attachments/assets/14fff3f1-9cf7-4db5-8501-9e4719f89133" />
<img width="700" height="450" alt="A5 Image Viewer adjustment board" src="https://github.com/user-attachments/assets/25185f12-ec5c-4368-8480-b4397875b543" />
<img width="400" height="300" alt="A5 Image Viewer crop board" src="https://github.com/user-attachments/assets/3859876b-8839-4f0c-ac84-5fe63f8ee458" />

## Personal note and disclaimer

This was created over a long time using ChatGPT and Codex. It will also be
maintained on GitHub with their help, but changes will only ever come from me;
there is no automated development running.

It began as a personal project because I started using local AI tools and my
image viewer of choice was crashing and freezing constantly. It was intended as
a personal image-viewer and editor best-of for my needs, but it has grown into a
real alternative.

I have no intention, now or in the future, of rivaling the feature and option
richness of larger projects such as FastStone, XnView, IrfanView, ACDSee, and
similar applications. These amazing professional projects will remain much
larger, more complete, and more flexible packages. This is essentially a very
personal best-of inspired by them and optimized for stability above everything
else.

It is an ongoing project, and sensible ideas, additions, and fixes are welcome.
The technical documentation below will likely be maintained and extended with
AI assistance.

## Installation

### Portable build

Download `A5ImageViewer-Portable-1.0.0.exe` from the latest release and place it
in any writable folder. No Python installation is required. The application
stores its `config.json` in that folder.

### Installer

Download and run `A5ImageViewer-Setup-1.0.0.exe`. The destination folder is
selectable. Windows integration and supported image-file associations are
optional installer choices. No Python installation is required.

The distributed executables are currently unsigned. Windows SmartScreen or
some antivirus products may therefore show a warning, particularly for the
single-file portable build. Download builds only from this repository's
Releases page.

### Run from source

The convenient launcher creates `.venv`, installs the runtime dependencies, and
starts the application:

```powershell
.\run.bat
```

The equivalent manual commands are:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Application preferences and recent paths are stored in the local `config.json`.
That file is intentionally not tracked.

## Building Windows executables

Run `build-exe.bat` for the portable executable or `build-installer.bat` for the
installer. On first use, either script creates the root `.venv` and installs the
dependencies in `requirements-build.txt`. The installer build also requires
Inno Setup 6 or 7.

Build results are written to the local `output_exe` directory. That directory is
ignored by Git; distributable builds belong on the GitHub Releases page.

The build scripts invoke PyInstaller directly. The local `PyToExe` directory and
third-party conversion frontend are not used or included.

## Testing

The test suite uses Python's standard `unittest` runner:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## Feedback

Use the GitHub Issues page for bug reports and focused feature suggestions.
Please include the Windows version, the build type, and clear reproduction steps
for bugs.

## License

Copyright (C) 2026 A5Projects.

Licensed under the GNU General Public License version 3. This keeps distributed
versions of the application and their source available under the same terms as
the GPL edition of PyQt6. See [LICENSE](LICENSE).
