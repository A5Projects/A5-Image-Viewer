@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "BUILD_ENV_SCRIPT=%ROOT_DIR%prepare-build-env.bat"
set "ENTRY_POINT=%ROOT_DIR%main.py"
set "ICON_FILE=%ROOT_DIR%A5ImageViewer.ico"
set "VERSION_FILE=%ROOT_DIR%installer\A5ImageViewer.version.txt"
set "OUTPUT_DIR=%ROOT_DIR%output_exe"
set "WORK_DIR=%ROOT_DIR%build\standalone"
set "SPEC_DIR=%ROOT_DIR%build\spec"
set "EXE_FILE=%OUTPUT_DIR%\!A5ImageViewer.exe"

if not exist "%BUILD_ENV_SCRIPT%" (
    set "BUILD_ERROR=The build environment helper was not found at: %BUILD_ENV_SCRIPT%"
    goto :failure
)

call "%BUILD_ENV_SCRIPT%"
if errorlevel 1 (
    set "BUILD_ERROR=The project build environment could not be prepared."
    goto :failure
)
set "BUILD_PYTHON=%A5_BUILD_PYTHON%"

if not exist "%ENTRY_POINT%" (
    set "BUILD_ERROR=Application entry point was not found at: %ENTRY_POINT%"
    goto :failure
)

if not exist "%ICON_FILE%" (
    set "BUILD_ERROR=Application icon was not found at: %ICON_FILE%"
    goto :failure
)

if not exist "%VERSION_FILE%" (
    set "BUILD_ERROR=Windows version metadata was not found at: %VERSION_FILE%"
    goto :failure
)

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo Building the current A5ImageViewer workspace...
echo.

pushd "%ROOT_DIR%" >nul
"%BUILD_PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "!A5ImageViewer" ^
    --icon "%ICON_FILE%" ^
    --version-file "%VERSION_FILE%" ^
    --add-data "%ICON_FILE%;." ^
    --distpath "%OUTPUT_DIR%" ^
    --workpath "%WORK_DIR%" ^
    --specpath "%SPEC_DIR%" ^
    --clean ^
    --noconfirm ^
    "%ENTRY_POINT%"
set "BUILD_EXIT=%ERRORLEVEL%"
popd >nul

if not "%BUILD_EXIT%"=="0" (
    set "BUILD_ERROR=PyInstaller failed with exit code %BUILD_EXIT%."
    goto :failure
)

if not exist "%EXE_FILE%" (
    set "BUILD_ERROR=PyInstaller completed, but the expected executable was not created: %EXE_FILE%"
    goto :failure
)

echo.
echo Build completed successfully:
echo %EXE_FILE%
goto :finish

:failure
echo.
echo ERROR: %BUILD_ERROR%
if /I not "%A5_BUILD_NO_PAUSE%"=="1" pause
exit /b 1

:finish
if /I not "%A5_BUILD_NO_PAUSE%"=="1" pause
exit /b 0
