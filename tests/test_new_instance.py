import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QMenu, QToolButton

from ui.main_window import MainWindow
from utils import application_launch, file_ops


class NewInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a5 instances ")
        self.addCleanup(self.temp.cleanup)
        config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        config_patch.start()
        self.addCleanup(config_patch.stop)
        file_ops.set_startup_behavior("empty")

    def test_frozen_launch_uses_same_executable_and_independent_bundle(self):
        executable = os.path.join(self.temp.name, "!A5ImageViewer.exe")
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", executable), \
                patch.object(application_launch, "QProcess") as factory:
            process = factory.return_value
            process.startDetached.return_value = (True, 123)
            before = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")
            application_launch.start_new_instance(self.temp.name)
            process.setProgram.assert_called_once_with(executable)
            process.setArguments.assert_called_once_with([self.temp.name])
            environment = process.setProcessEnvironment.call_args.args[0]
            self.assertEqual(environment.value("PYINSTALLER_RESET_ENVIRONMENT"), "1")
            self.assertEqual(os.environ.get("PYINSTALLER_RESET_ENVIRONMENT"), before)
            process.startDetached.assert_called_once_with()

    def test_source_launch_uses_main_script_and_separate_folder_argument(self):
        with patch.object(sys, "frozen", False, create=True), \
                patch.object(application_launch, "QProcess") as factory:
            factory.return_value.startDetached.return_value = (True, 123)
            application_launch.start_new_instance(self.temp.name)
            program = factory.return_value.setProgram.call_args.args[0]
            self.assertEqual(os.path.dirname(program), os.path.dirname(sys.executable))
            arguments = factory.return_value.setArguments.call_args.args[0]
            self.assertTrue(arguments[0].endswith("main.py"))
            self.assertTrue(os.path.isfile(arguments[0]))
            self.assertEqual(arguments[1:], [self.temp.name])

    def test_missing_folder_does_not_start_process(self):
        with patch.object(application_launch, "QProcess") as factory:
            with self.assertRaises(FileNotFoundError):
                application_launch.start_new_instance(os.path.join(self.temp.name, "missing"))
            factory.assert_not_called()

    def test_launch_failure_reports_process_error(self):
        with patch.object(application_launch, "QProcess") as factory:
            factory.return_value.startDetached.return_value = (False, 0)
            factory.return_value.errorString.return_value = "Access denied"
            with self.assertRaisesRegex(OSError, "Access denied"):
                application_launch.start_new_instance()

    def test_detached_source_child_survives_launcher_exit(self):
        root = Path(self.temp.name)
        (root / "main.py").write_text('''
import json, sys, time
from pathlib import Path
root = Path(__file__).parent
(root / "ready").write_text(json.dumps(sys.argv[1:]))
deadline = time.monotonic() + 10
while not (root / "continue").exists() and time.monotonic() < deadline:
    time.sleep(0.02)
(root / "done").write_text("finished")
''', encoding="utf-8")
        code = '''
import sys
from pathlib import Path
from PyQt6.QtCore import QCoreApplication
from utils import application_launch
app = QCoreApplication([])
application_launch.__file__ = str(Path(sys.argv[1]) / "utils" / "application_launch.py")
application_launch.start_new_instance(sys.argv[1])
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(root)],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        def wait_for(name):
            deadline = time.monotonic() + 5
            while not (root / name).exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((root / name).exists(), name)

        try:
            wait_for("ready")
            import json
            self.assertEqual(json.loads((root / "ready").read_text()), [str(root)])
        finally:
            (root / "continue").touch()
            wait_for("done")

    def test_config_is_released_and_sequential_process_changes_are_preserved(self):
        code = '''
import sys
from utils import file_ops
file_ops.CONFIG_FILE = sys.argv[1]
file_ops.set_startup_behavior("last_used")
print("ready", flush=True)
sys.stdin.readline()
assert file_ops.get_ui_theme() == "light"
file_ops.set_viewer_default_mode("windowed")
'''
        process = subprocess.Popen(
            [sys.executable, "-B", "-u", "-c", code, file_ops.CONFIG_FILE],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            # Renaming an open file would fail on Windows. The child remains
            # running here after writing and is waiting for the parent.
            moved = file_ops.CONFIG_FILE + ".moved"
            os.rename(file_ops.CONFIG_FILE, moved)
            os.rename(moved, file_ops.CONFIG_FILE)
            file_ops.set_ui_theme("light")
            output, error = process.communicate("continue\n", timeout=10)
            self.assertEqual(process.returncode, 0, output + error)
            self.assertEqual(file_ops.get_startup_behavior(), "last_used")
            self.assertEqual(file_ops.get_ui_theme(), "light")
            self.assertEqual(file_ops.get_viewer_default_mode(), "windowed")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_toolbar_and_folder_menu_launch_correct_folder_and_report_failure(self):
        window = MainWindow()
        try:
            self.app.processEvents()
            window.current_folder_path = self.temp.name
            folder = os.path.join(self.temp.name, "another folder")
            os.mkdir(folder)
            with patch("ui.main_window.start_new_instance") as launch:
                window.new_instance_action.trigger()
                launch.assert_called_once_with(self.temp.name)
                menu = QMenu(window)
                window.add_new_instance_folder_action(menu, folder).trigger()
                self.assertEqual(launch.call_args.args, (folder,))
            with patch("ui.main_window.start_new_instance", side_effect=OSError("test failure")), \
                    patch("ui.main_window.QMessageBox.warning") as warning:
                window.new_instance_action.trigger()
                warning.assert_called_once()
                self.assertIn("test failure", warning.call_args.args[2])
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()
            self.app.processEvents()

    def test_viewer_menu_is_compact_and_sync_button_is_removed(self):
        window = MainWindow()
        try:
            self.app.processEvents()
            viewer = window.fullscreen_viewer
            viewer.set_current_image_path(os.path.join(self.temp.name, "sample.png"))
            self.assertFalse(any(button.text() == "Show in browser"
                                 for button in viewer.findChildren(QToolButton)))
            menus = []
            with patch("ui.fullscreen_viewer.QMenu.exec", lambda menu, *args: menus.append(menu)):
                viewer.show_context_menu(QPoint(0, 0))
            menu = menus[0]
            actions = {action.text().split("\t")[0]: action for action in menu.actions()}
            self.assertEqual(actions["Next Image"].text(), "Next Image\tSpace")
            self.assertIn("PgDown", actions["Next Image"].toolTip())
            self.assertIn("P,", actions["Previous Image"].toolTip())
            self.assertTrue(menu.toolTipsVisible())
            compact_width = menu.sizeHint().width()
            compact_style = menu.styleSheet()
            menu.setStyleSheet("")
            self.assertLess(compact_width, menu.sizeHint().width())
            menu.setStyleSheet(compact_style)
            actions["Next Image"].setText("Next Image\tSpace / PgDown / N")
            actions["Previous Image"].setText("Previous Image\tPgUp / P")
            self.assertLess(compact_width, menu.sizeHint().width())
            with patch.object(window, "sync_browser_to_viewed_image") as sync:
                actions["Show in browser"].trigger()
                sync.assert_called_once()
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()
            self.app.processEvents()
