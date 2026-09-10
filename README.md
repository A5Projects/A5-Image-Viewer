# A5 Image Viewer

A fast, Windows-oriented image browser, fullscreen viewer, and lightweight
editor written in Python with PyQt6 and Pillow.

## Run from source

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
~~~

Application preferences and recent paths are stored in the local
**config.json**. That file is intentionally not tracked.

## Windows builds

- **output_exe/!A5ImageViewer.exe**: portable standalone build
- **output_exe/A5ImageViewer-Setup-1.0.0.exe**: installer with optional Windows
  file-association integration

The local **PyToExe** build environment and third-party conversion frontend are
not part of this repository. The project build scripts and Inno Setup sources
remain included.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
