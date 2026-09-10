import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu

from ui.main_window import MainWindow
from utils import windows_shell


class ShellHarness(MainWindow):
    def __init__(self):
        QMainWindow.__init__(self)
        self.current_image_path = None
        self.transfers = []

    def transfer_files_to_folder(self, paths, destination_folder, move_files=False):
        self.transfers.append((list(paths), destination_folder, move_files))


class WindowsShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_file(self, name):
        path = os.path.join(self.temp_dir.name, name)
        with open(path, "wb"):
            pass
        return path

    def test_send_to_listing_keeps_common_targets_and_filters_shell_handlers(self):
        app = self.make_file("Photoshop.lnk")
        executable = self.make_file("Tool.EXE")
        self.make_file("Compressed Folder.ZFSendToTarget")
        self.make_file("Mail Recipient.MAPIMail")
        self.make_file("Desktop shortcut.DeskLink")
        self.make_file("desktop.ini")
        folder = os.path.join(self.temp_dir.name, "Archive")
        os.mkdir(folder)

        with patch.object(windows_shell, "get_send_to_folder", return_value=self.temp_dir.name):
            targets = windows_shell.list_send_to_targets()

        self.assertEqual(
            [(target.display_name, target.kind) for target in targets],
            [("Archive", "folder"), ("Photoshop", "application"), ("Tool", "application")],
        )
        self.assertEqual(targets[1].path, app)
        self.assertEqual(targets[2].path, executable)

    def test_open_associated_file_passes_requested_verb(self):
        image = self.make_file("image.png")
        with (
            patch.object(windows_shell, "is_windows", return_value=True),
            patch.object(windows_shell, "_shell_execute", return_value=(True, "")) as execute,
        ):
            result = windows_shell.open_associated_file(image, verb="edit", owner_hwnd=42)

        self.assertEqual(result, (True, ""))
        execute.assert_called_once_with(image, verb="edit", owner_hwnd=42)

    def test_print_file_uses_registered_print_verb(self):
        image = self.make_file("image.png")
        with patch.object(
            windows_shell, "open_associated_file", return_value=(True, "")
        ) as open_file:
            result = windows_shell.print_file(image, owner_hwnd=19)

        self.assertEqual(result, (True, ""))
        open_file.assert_called_once_with(image, verb="print", owner_hwnd=19)

    def test_set_wallpaper_calls_windows_system_api(self):
        image = self.make_file("wallpaper.png")

        class FakeSystemParametersInfo:
            def __init__(self):
                self.argtypes = None
                self.restype = None
                self.calls = []

            def __call__(self, action, parameter, path_buffer, flags):
                self.calls.append((action, parameter, path_buffer.value, flags))
                return True

        operation = FakeSystemParametersInfo()
        user32 = type("FakeUser32", (), {"SystemParametersInfoW": operation})()
        with (
            patch.object(windows_shell, "is_windows", return_value=True),
            patch.object(windows_shell.ctypes, "WinDLL", return_value=user32),
        ):
            result = windows_shell.set_desktop_wallpaper(image)

        self.assertEqual(result, (True, ""))
        self.assertEqual(operation.calls[0][0], windows_shell.SPI_SETDESKWALLPAPER)
        self.assertEqual(operation.calls[0][2], os.path.abspath(image))
        self.assertEqual(
            operation.calls[0][3],
            windows_shell.SPIF_UPDATEINIFILE | windows_shell.SPIF_SENDCHANGE,
        )

    def test_application_send_to_quotes_paths_and_preserves_order(self):
        target_path = self.make_file("Viewer.lnk")
        first = self.make_file("first file.png")
        second = self.make_file("second.png")
        target = windows_shell.SendToTarget(target_path, "Viewer", "application")

        with (
            patch.object(windows_shell, "is_windows", return_value=True),
            patch.object(windows_shell, "_shell_execute", return_value=(True, "")) as execute,
        ):
            result = windows_shell.launch_send_to_target(target, [first, second], owner_hwnd=7)

        self.assertEqual(result, (True, ""))
        call = execute.call_args
        self.assertEqual(call.args[0], target_path)
        self.assertLess(call.kwargs["parameters"].find("first file.png"), call.kwargs["parameters"].find("second.png"))
        self.assertEqual(call.kwargs["owner_hwnd"], 7)

    def test_application_send_to_rejects_oversized_arguments(self):
        target_path = self.make_file("Viewer.lnk")
        image = self.make_file("long-name.png")
        target = windows_shell.SendToTarget(target_path, "Viewer", "application")

        with (
            patch.object(windows_shell, "is_windows", return_value=True),
            patch.object(windows_shell, "MAX_SHELL_PARAMETERS", 3),
            patch.object(windows_shell, "_shell_execute") as execute,
        ):
            success, error = windows_shell.launch_send_to_target(target, [image])

        self.assertFalse(success)
        self.assertIn("too long", error)
        execute.assert_not_called()

    def test_ui_open_menu_and_send_to_folder_are_selection_safe(self):
        image = self.make_file("image.png")
        destination = os.path.join(self.temp_dir.name, "destination")
        os.mkdir(destination)
        target = windows_shell.SendToTarget(destination, "destination", "folder")
        harness = ShellHarness()
        menu = QMenu(harness)
        try:
            with patch.object(windows_shell, "is_windows", return_value=True):
                open_menu = harness.add_open_with_menu(menu, image)
            self.assertEqual(
                [action.text() for action in open_menu.actions()],
                ["Associated program\tF3", "Associated editor\tF4"],
            )

            self.assertTrue(harness.send_files_to_target(target, [image]))
            self.assertEqual(harness.transfers, [([image], destination, False)])
        finally:
            harness.close()

    def test_send_to_menu_preserves_selected_path_order(self):
        first = self.make_file("first.png")
        second = self.make_file("second.png")
        target_path = self.make_file("Viewer.lnk")
        target = windows_shell.SendToTarget(target_path, "Viewer", "application")
        harness = ShellHarness()
        menu = QMenu(harness)
        try:
            with (
                patch.object(windows_shell, "is_windows", return_value=True),
                patch.object(windows_shell, "list_send_to_targets", return_value=[target]),
                patch.object(harness, "send_files_to_target", return_value=True) as send,
            ):
                send_menu = harness.add_send_to_menu(menu, [first, second])
                send_menu.actions()[0].trigger()

            self.assertEqual(send.call_args.args[0], target)
            self.assertEqual(send.call_args.args[1], (first, second))
        finally:
            harness.close()

    def test_non_windows_open_menu_hides_editor(self):
        image = self.make_file("image.png")
        harness = ShellHarness()
        menu = QMenu(harness)
        try:
            with patch.object(windows_shell, "is_windows", return_value=False):
                open_menu = harness.add_open_with_menu(menu, image)
            self.assertEqual(
                [action.text() for action in open_menu.actions()],
                ["Associated program\tF3"],
            )
        finally:
            harness.close()

    def test_windows_image_actions_route_print_and_wallpaper(self):
        image = self.make_file("image.png")
        harness = ShellHarness()
        menu = QMenu(harness)
        try:
            with (
                patch.object(windows_shell, "is_windows", return_value=True),
                patch.object(harness, "print_image", return_value=True) as print_image,
                patch.object(
                    harness, "set_image_as_wallpaper", return_value=True
                ) as wallpaper,
            ):
                actions = harness.add_windows_image_actions(menu, image)
                actions[0].trigger()
                actions[1].trigger()

            print_image.assert_called_once_with(image, parent_override=None)
            wallpaper.assert_called_once_with(image, parent_override=None)
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
