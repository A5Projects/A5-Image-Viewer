# A5 Image Viewer

A fast, Windows-oriented image browser, fullscreen viewer, and lightweight
editor written in Python with PyQt6 and Pillow.

1. The leading directive was not a vast amount of features, but stability and responsivness, even under heavy system, GPU and Vram load (local AI, games - My previous fav. was freezing and crashing).  The Features grew nonetheless, into a personal best of, but only under that guiding rule. 
- VERY low/no Vram use (that was paramount throughout)
- Minimum needed dependencies. For size and stability reasons. (If in doubt, fancy feature ideas were dropped, example more image adjusting options) 
- Functional UI. Three UI modes (Dark, medium, light).
- - THE UI, the shortkeys and what is and isn't available. It is very much MY best of. Focus fast, one button workflow.
- Adjustable performance (cpu use, ram use) for thumbnail mode. Without going crazy on settings. 
- Very basic file manager options(rename, new folder, open in explorer)
- - Basic but fast copying options: copy to (folder), move to, (with remembered paths), with visual overwrite/renaming dialog, including auto renaming options. Also copy/cut/paste, drag and drop of files and image)
- Single button shortcuts. Visible in context menu.
- very fast, efficient Crop Board, to crop many images fast and efficient. (under the hood and in UI. Which is VERY much based on my priorities).
- Image adjustments in size, and visuals, with simple functional UI, some QOL options like maiantaining settings) CPU based.
Batch conversion and batch rename of images.
- QoL features like optional automatic, renaming and numbering options, for crop and image adjust.
  

- since i use Windows, That was priority. no precaution was taken to make it linux compatible, despite the python base.
- But it should not be the biggest job in the world to make that work for most features.

Quick start (Windows):
--
1. A5ImageViewer-Portable-1.0.0.exe to run it locally, as completely portable version without any installation or system changes. It will create the config.json next to it but nothing else.
2. A5ImageViewer-Setup-1.0.0.exe For a classic installer, integrating (optionally) better into windows as app.
3. Python based: Use run.bat, it sets all up (python environment and dependencies) and starts it. It just starts it after that. This DOES require a system python 3 on path to create the .venv environment on first run

   The .exe versions are up to date. But can be created too. (See extended instructions below).

<img width="930" height="640" alt="A5viewer-main-1" src="https://github.com/user-attachments/assets/14fff3f1-9cf7-4db5-8501-9e4719f89133" />
<img width="700" height="450" alt="A5viewerImg adjust-1" src="https://github.com/user-attachments/assets/25185f12-ec5c-4368-8480-b4397875b543" />
<img width="400" height="300" alt="A5Imagev-Cropboard1" src="https://github.com/user-attachments/assets/3859876b-8839-4f0c-ac84-5fe63f8ee458" />

2. Installation

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
