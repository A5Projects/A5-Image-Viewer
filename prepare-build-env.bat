@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "BUILD_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BUILD_REQUIREMENTS=%ROOT_DIR%requirements-build.txt"

if not exist "%BUILD_REQUIREMENTS%" (
    set "BUILD_ERROR=Build requirements were not found at: %BUILD_REQUIREMENTS%"
    goto :failure
)

if not exist "%BUILD_PYTHON%" (
    echo Creating the project build environment...
    set "VENV_READY="

    where py.exe >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%VENV_DIR%"
        if not errorlevel 1 set "VENV_READY=1"
    )

    if not defined VENV_READY (
        where python.exe >nul 2>&1
        if errorlevel 1 (
            set "BUILD_ERROR=Python 3 was not found. Install Python and run the build again."
            goto :failure
        )
        python -m venv "%VENV_DIR%"
        if errorlevel 1 (
            set "BUILD_ERROR=Python could not create the virtual environment at: %VENV_DIR%"
            goto :failure
        )
    )
)

if not exist "%BUILD_PYTHON%" (
    set "BUILD_ERROR=The virtual environment is missing Python at: %BUILD_PYTHON%"
    goto :failure
)

"%BUILD_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%BUILD_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 (
        set "BUILD_ERROR=pip could not be initialized in: %VENV_DIR%"
        goto :failure
    )
)

"%BUILD_PYTHON%" -c "import PIL, PyQt6, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing build dependencies...
    "%BUILD_PYTHON%" -m pip install --disable-pip-version-check -r "%BUILD_REQUIREMENTS%"
    if errorlevel 1 (
        set "BUILD_ERROR=The build dependencies could not be installed."
        goto :failure
    )
)

"%BUILD_PYTHON%" -c "import PIL, PyQt6, PyInstaller" >nul 2>&1
if errorlevel 1 (
    set "BUILD_ERROR=The build environment is incomplete after installation."
    goto :failure
)

endlocal & set "A5_BUILD_PYTHON=%BUILD_PYTHON%"
exit /b 0

:failure
echo.
echo ERROR: %BUILD_ERROR%
endlocal
exit /b 1
