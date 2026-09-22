"""Require a successful startup of the actual frozen app before distributing it."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from build_app import clean_environment


def main():
    executable = Path(sys.argv[1]).resolve()
    env = clean_environment(include_python=False)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    with tempfile.TemporaryDirectory(prefix="a5-exe-check-") as folder:
        report = Path(folder) / "startup.json"
        try:
            result = subprocess.run(
                [str(executable), "--self-test", str(report)],
                cwd=folder, env=env, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            data = json.loads(report.read_text(encoding="utf-8"))
            if result.returncode or data.get("ok") is not True:
                raise RuntimeError(data.get("error", f"Exit code {result.returncode}"))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"Executable startup check FAILED: {exc}", file=sys.stderr)
            return 1
    print(f"Executable startup check passed: {executable.name} (Qt {data['qt_version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
