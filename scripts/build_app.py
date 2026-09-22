"""Run PyInstaller without collecting DLLs from unrelated tools on PATH."""

import os
from pathlib import Path
import subprocess
import sys


def clean_environment(include_python=True):
    env = os.environ.copy()
    if sys.platform == "win32":
        windows = Path(os.environ["SystemRoot"])
        paths = [windows / "System32", windows]
        if include_python:
            paths.extend((Path(sys.executable).parent, Path(sys.base_prefix)))
        env["PATH"] = os.pathsep.join(map(str, paths))
    for name in (
        "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH",
    ):
        env.pop(name, None)
    return env


if __name__ == "__main__":
    sys.exit(subprocess.call(
        [sys.executable, "-m", "PyInstaller", *sys.argv[1:]],
        env=clean_environment(),
    ))
