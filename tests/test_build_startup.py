import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_app import clean_environment
from utils.startup_check import run_startup_check


class BuildStartupTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows DLL search")
    def test_build_search_excludes_unrelated_dll_directories(self):
        with patch.dict(os.environ, {
            "PATH": r"C:\unrelated\poppler;C:\unrelated\Qt",
            "PYTHONPATH": r"C:\unrelated\python",
            "QT_PLUGIN_PATH": r"C:\unrelated\plugins",
            "PYINSTALLER_CONFIG_DIR": r"C:\build-cache",
        }):
            env = clean_environment()
            self.assertNotIn("unrelated", env["PATH"])
            self.assertEqual(Path(env["PATH"].split(os.pathsep)[0]),
                             Path(os.environ["SystemRoot"]) / "System32")
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("QT_PLUGIN_PATH", env)
            self.assertEqual(env["PYINSTALLER_CONFIG_DIR"], r"C:\build-cache")
            self.assertIn("unrelated", os.environ["PATH"])
            self.assertEqual(len(clean_environment(include_python=False)["PATH"].split(os.pathsep)), 2)

    def test_import_failure_is_reported_without_a_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            with patch("utils.startup_check._check_startup",
                       side_effect=ImportError("DLL load failed while importing QtWidgets")):
                self.assertEqual(run_startup_check(report), 1)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(data["ok"])
            self.assertIn("DLL load failed while importing QtWidgets", data["error"])

    def test_startup_check_runs_with_an_isolated_configuration(self):
        root = Path(__file__).resolve().parent.parent
        config = root / "config.json"
        before = config.read_bytes() if config.exists() else None
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            result = subprocess.run(
                [sys.executable, "-B", str(root / "main.py"), "--self-test", str(report)],
                cwd=folder, env=clean_environment(), capture_output=True,
                text=True, timeout=45,
            )
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 0, data.get("error", result.stderr))
            self.assertTrue(data["ok"])
            self.assertEqual(data["platform"], "windows" if sys.platform == "win32" else "offscreen")
        self.assertEqual(config.read_bytes() if config.exists() else None, before)


if __name__ == "__main__":
    unittest.main()
