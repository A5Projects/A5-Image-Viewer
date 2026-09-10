A5ImageViewer installer build
==============================

Run build-installer.bat from the workspace root. It creates a PyInstaller
onedir build and compiles it with Inno Setup.

Build-time requirements:
- Python 3 available through py.exe or python.exe
- Inno Setup 7 or 6 (ISCC.exe)

The build script creates or reuses .venv in the workspace root and installs
requirements-build.txt when Pillow, PyQt6, or PyInstaller is missing. It does
not use auto-py-to-exe or the local PyToExe directory.

Output:
output_exe\A5ImageViewer-Setup-1.0.0.exe

The selected installation folder directly contains A5ImageViewer.exe,
_internal, and config.json. Upgrades replace the executable and runtime while
preserving config.json. To override the Inno Setup compiler location, set
ISCC_EXE before running the BAT file.
