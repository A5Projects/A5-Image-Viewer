@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "BUILD_ENV_SCRIPT=%ROOT_DIR%prepare-build-env.bat"
set "ENTRY_POINT=%ROOT_DIR%main.py"
set "ICON_FILE=%ROOT_DIR%A5ImageViewer.ico"
set "VERSION_FILE=%ROOT_DIR%installer\A5ImageViewer.version.txt"
set "INSTALLER_SCRIPT=%ROOT_DIR%installer\A5ImageViewer.iss"
set "STAGING_DIR=%ROOT_DIR%installer\staging"
set "WORK_DIR=%ROOT_DIR%installer\build"
set "SPEC_DIR=%ROOT_DIR%installer\spec"
set "OUTPUT_DIR=%ROOT_DIR%output_exe"
set "APP_VERSION=1.0.0"

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

for %%F in ("%ENTRY_POINT%" "%ICON_FILE%" "%VERSION_FILE%" "%INSTALLER_SCRIPT%") do (
    if not exist "%%~F" (
        set "BUILD_ERROR=Required build input was not found: %%~F"
        goto :failure
    )
)

if defined ISCC_EXE if exist "%ISCC_EXE%" set "INNO_COMPILER=%ISCC_EXE%"
if not defined INNO_COMPILER if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "INNO_COMPILER=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined INNO_COMPILER if exist "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe" set "INNO_COMPILER=%LocalAppData%\Programs\Inno Setup 7\ISCC.exe"
if not defined INNO_COMPILER if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "INNO_COMPILER=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined INNO_COMPILER if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "INNO_COMPILER=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined INNO_COMPILER if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "INNO_COMPILER=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined INNO_COMPILER (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined INNO_COMPILER set "INNO_COMPILER=%%I"
)
if not defined INNO_COMPILER (
    set "BUILD_ERROR=Inno Setup was not found. Install Inno Setup 7 or set ISCC_EXE to the full path of ISCC.exe."
    goto :failure
)

echo Building the A5ImageViewer onedir application...
echo.

if exist "%STAGING_DIR%" rmdir /s /q "%STAGING_DIR%"
if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
if exist "%SPEC_DIR%" rmdir /s /q "%SPEC_DIR%"
if not exist "%STAGING_DIR%" mkdir "%STAGING_DIR%"
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
if not exist "%SPEC_DIR%" mkdir "%SPEC_DIR%"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

pushd "%ROOT_DIR%" >nul
"%BUILD_PYTHON%" -m PyInstaller ^
    --onedir ^
    --windowed ^
    --name "A5ImageViewer" ^
    --icon "%ICON_FILE%" ^
    --version-file "%VERSION_FILE%" ^
    --add-data "%ICON_FILE%;." ^
    --distpath "%STAGING_DIR%" ^
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

if not exist "%STAGING_DIR%\A5ImageViewer\A5ImageViewer.exe" (
    set "BUILD_ERROR=The onedir executable was not created."
    goto :failure
)

echo.
echo Compiling the Windows installer...
"%INNO_COMPILER%" /DMyAppVersion=%APP_VERSION% "%INSTALLER_SCRIPT%"
set "BUILD_EXIT=%ERRORLEVEL%"
if not "%BUILD_EXIT%"=="0" (
    set "BUILD_ERROR=Inno Setup failed with exit code %BUILD_EXIT%."
    goto :failure
)

set "SETUP_FILE=%OUTPUT_DIR%\A5ImageViewer-Setup-%APP_VERSION%.exe"
if not exist "%SETUP_FILE%" (
    set "BUILD_ERROR=Setup completed, but the expected installer was not created: %SETUP_FILE%"
    goto :failure
)

echo.
echo Installer build completed successfully:
echo %SETUP_FILE%
goto :finish

:failure
echo.
echo ERROR: %BUILD_ERROR%
if /I not "%A5_BUILD_NO_PAUSE%"=="1" pause
exit /b 1

:finish
if /I not "%A5_BUILD_NO_PAUSE%"=="1" pause
exit /b 0
