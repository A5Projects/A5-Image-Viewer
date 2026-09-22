"""Launch another independent copy of the current application."""

import os
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment


def start_new_instance(folder_path=None):
    folder = os.path.abspath(folder_path) if folder_path else None
    if folder and not os.path.isdir(folder):
        raise FileNotFoundError(f"Folder does not exist:\n{folder}")

    program = sys.executable
    arguments = []
    environment = QProcessEnvironment.systemEnvironment()
    if getattr(sys, "frozen", False):
        # In particular, a portable one-file child must own its extracted
        # files so it can continue after the original instance closes.
        environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
    else:
        pythonw = os.path.join(os.path.dirname(program), "pythonw.exe")
        if os.name == "nt" and os.path.isfile(pythonw):
            program = pythonw
        arguments.append(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
        ))
    if folder:
        arguments.append(folder)

    process = QProcess()
    process.setProgram(program)
    process.setArguments(arguments)
    process.setWorkingDirectory(os.path.dirname(program))
    process.setProcessEnvironment(environment)
    # The new GUI instance does not use the original instance's standard streams.
    process.setStandardInputFile(QProcess.nullDevice())
    process.setStandardOutputFile(QProcess.nullDevice())
    process.setStandardErrorFile(QProcess.nullDevice())
    started, _pid = process.startDetached()
    if not started:
        raise OSError(f"Could not start another instance: {process.errorString()}")
