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

Run **build-exe.bat** for the portable executable or **build-installer.bat**
for the installer. On first use, either script creates the root **.venv** and
installs the dependencies in **requirements-build.txt**. The installer build
also requires Inno Setup 6 or 7.

The build scripts invoke PyInstaller directly. The local **PyToExe** directory
and third-party conversion frontend are not used or included.

## License

Copyright (C) 2026 A5Projects.

Licensed under the GNU General Public License version 3. This keeps distributed
versions of the application and their source available under the same terms as
the GPL edition of PyQt6. See [LICENSE](LICENSE).
