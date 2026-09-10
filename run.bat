@echo off
set VENV_DIR=.venv

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
)

echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"

echo Installing dependencies...
pip install -r requirements.txt

echo Starting A5ImageViewer...
.\.venv\Scripts\python main.py

pause
