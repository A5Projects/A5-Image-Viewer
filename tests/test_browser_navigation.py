import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QShortcut, QStandardItem
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.dialogs import CopyMoveDialog
from ui.thumbnail_view import EXT_ROLE, KIND_ROLE, PATH_ROLE, WIDTH_ROLE, thumbnail_item_label
from utils import file_ops


class BrowserNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", str(Path(self.temp.name) / "config.json"))
        self.config_patch.start()
        file_ops.set_startup_behavior("empty")
        self.window = MainWindow()
        self.window.show()
        self.window.activateWindow()
        self.view = self.window.thumbnail_view
        self.view.selectionModel().currentChanged.disconnect(self.window.on_thumbnail_selected)
        self.app.processEvents()
        self.view.setFocus()

    def tearDown(self):
        self.view.shutdown()
        self.window.crop_prefetch_service.shutdown()
        self.window.transfer_coordinator.shutdown()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.config_patch.stop()
        self.temp.cleanup()

    def add_names(self, names):
        for name in names:
            item = QStandardItem(thumbnail_item_label(name, "png", "image", width=640, height=480))
            item.setData(str(Path(self.temp.name) / name), PATH_ROLE)
            item.setData("image", KIND_ROLE)
            item.setData("png", EXT_ROLE)
            self.view.thumbnail_model.appendRow(item)
            self.view.register_item(item)
        self.view.setCurrentIndex(self.view.model().index(0, 0))
        self.app.processEvents()

    def shortcut_spy(self, keys):
        shortcut = next(s for s in self.window.findChildren(QShortcut)
                        if s.parent() is self.window and s.key().toString() == keys)
        shortcut.activated.disconnect()
        spy = Mock()
        shortcut.activated.connect(spy)
        return spy

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_swipe_navigation_is_scoped_to_thumbnail_view(self):
        from tests.test_swipe_navigation import wheel
        with patch.object(self.window, "go_back_folder") as back, patch.object(self.window, "go_forward_folder") as forward:
            for phase, x in ((Qt.ScrollPhase.ScrollBegin, 0), (Qt.ScrollPhase.ScrollUpdate, 100),
                             (Qt.ScrollPhase.ScrollUpdate, 200), (Qt.ScrollPhase.ScrollEnd, 0)):
                self.app.sendEvent(self.view.viewport(), wheel(x, phase=phase))
            back.assert_called_once()
            self.app.sendEvent(self.view.viewport(), wheel(phase=Qt.ScrollPhase.ScrollBegin))
            self.app.sendEvent(self.view.viewport(), wheel(-100, phase=Qt.ScrollPhase.ScrollUpdate))
            forward.assert_called_once()
            self.app.sendEvent(self.window.tree_view.viewport(), wheel(100))
            back.assert_called_once()

    def test_vertical_wheel_still_scrolls_thumbnail_view(self):
        from tests.test_swipe_navigation import wheel
        self.add_names([f"image-{i}.png" for i in range(100)])
        self.view.doItemsLayout()
        with patch.object(self.window, "go_back_folder") as back, patch.object(self.window, "go_forward_folder") as forward:
            self.app.sendEvent(self.view.viewport(), wheel(0, -120, pixels=False))
            self.assertGreater(self.view.verticalScrollBar().value(), 0)
            back.assert_not_called()
            forward.assert_not_called()

    def test_dedicated_history_keys(self):
        back = self.shortcut_spy("Back")
        forward = self.shortcut_spy("Forward")
        QTest.keyClick(self.view, Qt.Key.Key_Back)
        QTest.keyClick(self.view, Qt.Key.Key_Forward)
        self.assertEqual(back.call_count, 1)
        self.assertEqual(forward.call_count, 1)
        for shortcut in self.window.findChildren(QShortcut):
            if shortcut.key().toString() in ("Back", "Forward"):
                self.assertFalse(shortcut.autoRepeat())

    def test_switching_folders_with_active_decoders_keeps_current_images(self):
        self.view.selectionModel().currentChanged.connect(self.window.on_thumbnail_selected)
        folders = []
        for number, color in enumerate(("red", "green", "blue"), start=1):
            folder = Path(self.temp.name) / f"folder-{number}"
            folder.mkdir()
            folders.append(folder)
            image = QImage(320 * number, 240, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            first = folder / "image-00.png"
            self.assertTrue(image.save(str(first)))
            data = first.read_bytes()
            for index in range(1, 80):
                (folder / f"image-{index:02}.png").write_bytes(data)

        # Exercise real scanning, thumbnail workers and preview decoding while
        # moving on before the previous folder has finished populating.
        for folder in folders * 3:
            self.window.navigate_to_folder(str(folder))
            self.wait_until(lambda: not self.view.loading)
            self.window.select_image_by_path(str(folder / "image-00.png"))
            self.assertEqual(Path(self.window.current_folder_path), folder)
            self.assertEqual(Path(self.window.current_image_path).parent, folder)
            self.app.processEvents()
        self.window.folder_navigation_buttons["back"].click()
        self.assertEqual(Path(self.window.current_folder_path), folders[1])
        self.window.folder_navigation_buttons["forward"].click()
        self.assertEqual(Path(self.window.current_folder_path), folders[2])
        self.wait_until(lambda: not self.view.loading)
        self.window.select_image_by_path(str(folders[2] / "image-00.png"))
        self.wait_until(lambda: all(
            self.view.model().item(row).data(WIDTH_ROLE) == 960
            for row in range(self.view.model().rowCount())
        ))
        self.assertEqual(self.view.model().rowCount(), 80)
        self.assertTrue(all(Path(path).parent == folders[2] for path in self.view.path_items))
        self.assertEqual(Path(self.window.current_image_path), folders[2] / "image-00.png")

    def test_arrow_expansion_keeps_selection_and_does_not_load_thumbnails(self):
        root = Path(self.temp.name)
        branch = root / "branch"
        child = branch / "child"
        child.mkdir(parents=True)
        sibling = root / "sibling"
        sibling.mkdir()
        tree, model = self.window.tree_view, self.window.file_model
        root_index = model.index(str(root))
        tree.setRootIndex(root_index)
        self.wait_until(lambda: model.rowCount(root_index) == 2)
        tree.setCurrentIndex(model.index(str(sibling)))
        target = model.index(str(branch))
        tree.scrollTo(target)
        self.app.processEvents()
        rect = tree.visualRect(target)
        with patch.object(self.window, "load_current_folder") as load:
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(
                rect.left() - tree.indentation() // 2, rect.center().y()
            ))
            self.wait_until(lambda: tree.isExpanded(target) and model.rowCount(target) == 1)
            self.assertEqual(model.filePath(tree.currentIndex()), str(sibling).replace("\\", "/"))
            load.assert_not_called()
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(rect.left() + 35, rect.center().y()))
            load.assert_called_once()
            self.assertEqual(Path(self.window.current_folder_path), branch)

    def test_address_buttons_navigate_history_and_clear_forward_branch(self):
        buttons = self.window.folder_navigation_buttons
        self.assertTrue(all(not button.isEnabled() for button in buttons.values()))
        root = Path(self.temp.name)
        first, second, third = [root / name for name in ("first", "second", "third")]
        for folder in (first, second, third):
            folder.mkdir()
        with patch.object(self.window, "load_current_folder"):
            self.window.navigate_to_folder(str(first))
            self.assertFalse(buttons["back"].isEnabled())
            self.window.navigate_to_folder(str(second))
            self.assertTrue(buttons["back"].isEnabled())
            self.assertFalse(buttons["forward"].isEnabled())
            QTest.mouseClick(buttons["back"], Qt.MouseButton.LeftButton)
            self.assertEqual(Path(self.window.current_folder_path), first)
            self.assertFalse(buttons["back"].isEnabled())
            self.assertTrue(buttons["forward"].isEnabled())
            QTest.mouseClick(buttons["forward"], Qt.MouseButton.LeftButton)
            self.assertEqual(Path(self.window.current_folder_path), second)
            self.assertFalse(buttons["forward"].isEnabled())
            QTest.mouseClick(buttons["back"], Qt.MouseButton.LeftButton)
            self.window.navigate_to_folder(str(third))
            self.assertFalse(buttons["forward"].isEnabled())
            self.assertEqual([Path(path) for path in self.window.navigation_history], [first, third])

    def test_settings_limit_the_live_address_bar_and_both_destination_dialogs(self):
        folders = [Path(self.temp.name) / str(n) for n in range(4)]
        for folder in folders:
            folder.mkdir()
            file_ops.add_recent_folder(str(folder))
        with patch.object(self.window, "load_current_folder"):
            for folder in folders[:3]:
                self.window.navigate_to_folder(str(folder))
            self.window.navigate_to_folder(str(folders[0]))

            def set_limits():
                dialog = self.app.activeModalWidget()
                dialog.visited_limit_spin.setValue(2)
                dialog.destination_limit_spin.setValue(1)
                dialog.accept()

            QTimer.singleShot(0, set_limits)
            self.window.open_settings_dialog()
            bar = self.window.address_bar
            self.assertEqual([Path(bar.itemText(i)) for i in range(bar.count())], [folders[0], folders[2]])
            self.assertEqual(Path(self.window.current_folder_path), folders[0])
            bar.setEditText(str(folders[3]))
            QTest.keyClick(bar.lineEdit(), Qt.Key.Key_Return)
            self.assertEqual([Path(bar.itemText(i)) for i in range(bar.count())], [folders[3], folders[0]])
            self.assertEqual(file_ops.get_address_folders(), [str(folders[3]), str(folders[0])])
        for is_move in (False, True):
            dialog = CopyMoveDialog(self.window, is_move=is_move)
            self.assertEqual(dialog.list_widget.count(), 1)
            self.assertEqual(Path(dialog.list_widget.item(0).text()), folders[3])
            dialog.close()

    def test_address_history_checks_offline_folders_only_on_use(self):
        current, offline, oldest, new = [Path(self.temp.name) / name for name in ("a", "b", "c", "d")]
        for folder in (current, oldest, new):
            folder.mkdir()
        file_ops.set_folder_history_limits(3, 30)
        for folder in (oldest, offline, current):
            file_ops.add_address_folder(str(folder))
        bar = self.window.address_bar
        with patch("ui.main_window.os.path.isdir", side_effect=AssertionError("unexpected history probe")):
            self.window.load_address_history()
            self.assertEqual([Path(bar.itemText(i)) for i in range(bar.count())], [current, offline, oldest])
        with patch("ui.main_window.QMessageBox.warning") as warning:
            self.window.on_address_selected(1)
        warning.assert_called_once()
        self.assertIn(str(offline), warning.call_args.args[2])
        self.window.remember_folder(str(new))
        self.assertEqual([Path(bar.itemText(i)) for i in range(bar.count())], [new, current, offline])
        offline.mkdir()
        self.window.on_address_selected(2)
        self.assertEqual([Path(bar.itemText(i)) for i in range(bar.count())], [offline, new, current])

    def test_videos_require_opt_in_even_with_pending_thumbnail_requests(self):
        path = str(Path(self.temp.name) / "clip.mp4")
        Path(path).touch()
        grabber = self.window.video_frame_grabber
        self.assertFalse(self.window.show_videos_action.isChecked())
        with patch.object(grabber, "_ensure_backend", return_value=False) as initialize:
            self.window.navigate_to_folder(self.temp.name)
            generation = self.view.load_generation
            grabber.set_thumbnail_queue(generation, [path])
            grabber.prioritize(generation, [path])
            grabber.grab(path)
            self.app.processEvents()
            initialize.assert_not_called()
            self.assertIsNone(self.view.item_for_path(path))

            self.window.show_videos_action.setChecked(True)
            self.wait_until(lambda: initialize.called)
            self.assertIsNotNone(self.view.item_for_path(path))
            initialize.reset_mock()
            grabber.failed_paths.clear()
            self.window.show_menu.show()
            grabber.prioritize(self.view.load_generation, [path])
            self.window.show_videos_action.setChecked(False)
            grabber.prioritize(self.view.load_generation, [path])
            grabber.grab(path)
            self.app.processEvents()
            initialize.assert_not_called()
            self.assertFalse(grabber.pending_paths)
            self.assertIsNone(grabber.current_path)
            self.assertFalse(grabber.timer.isActive())
            self.window.show_menu.hide()

    def test_up_button_works_from_address_field_but_backspace_still_edits_text(self):
        root = Path(self.temp.name)
        child = root / "child"
        child.mkdir()
        buttons = self.window.folder_navigation_buttons
        with patch.object(self.window, "load_current_folder"):
            self.window.navigate_to_folder(str(child))
            self.assertTrue(buttons["up"].isEnabled())
            edit = self.window.address_bar.lineEdit()
            edit.setFocus()
            edit.setText("test")
            QTest.keyClick(edit, Qt.Key.Key_Backspace)
            self.assertEqual(edit.text(), "tes")
            self.assertEqual(Path(self.window.current_folder_path), child)
            QTest.mouseClick(buttons["up"], Qt.MouseButton.LeftButton)
            self.assertEqual(Path(self.window.current_folder_path), root)
            self.window.navigate_to_folder(root.anchor)
            self.assertFalse(buttons["up"].isEnabled())

    def test_alt_letters_cycle_in_display_order_without_activating_plain_shortcuts(self):
        self.add_names(["alpha.png", "Hotel.png", "hello.png"])
        flip = self.shortcut_spy("H")
        for expected in (1, 2, 1):
            QTest.keyClick(self.view, Qt.Key.Key_H, Qt.KeyboardModifier.AltModifier)
            self.assertEqual(self.view.currentIndex().row(), expected)
            self.assertEqual(len(self.view.selectionModel().selectedIndexes()), 1)
        flip.assert_not_called()
        QTest.keyClick(self.view, Qt.Key.Key_H)
        flip.assert_called_once()

    def test_all_top_row_numbers_match_names_instead_of_resolution_labels(self):
        self.add_names(["alpha.png"] + [f"{digit}_image.png" for digit in range(10)])
        for digit in range(10):
            with self.subTest(digit=digit):
                QTest.keyClick(self.view, Qt.Key(Qt.Key.Key_0 + digit), Qt.KeyboardModifier.AltModifier)
                self.assertEqual(self.view.currentIndex().row(), digit + 1)

    def test_hidden_names_are_skipped_and_no_match_preserves_selection(self):
        self.add_names(["alpha.png", "hotel.png", "hello.png", "hello_again.png"])
        self.view.set_filter_text("hello")
        for expected in (2, 3, 2):
            QTest.keyClick(self.view, Qt.Key.Key_H, Qt.KeyboardModifier.AltModifier)
            self.assertEqual(self.view.currentIndex().row(), expected)
        QTest.keyClick(self.view, Qt.Key.Key_Z, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.view.currentIndex().row(), 2)
        self.assertEqual(self.view.filter_text, "hello")

    def test_control_shortcuts_history_and_altgr_are_not_filename_navigation(self):
        self.add_names(["alpha.png", "hello.png"])
        copy = self.shortcut_spy("Ctrl+C")
        back = self.shortcut_spy("Alt+Left")
        with patch.object(self.view, "jump_to_filename") as jump:
            QTest.keyClick(self.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(self.view, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
            QTest.keyClick(self.view, Qt.Key.Key_H,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            QTest.keyClick(self.view, Qt.Key.Key_1,
                           Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.KeypadModifier)
            jump.assert_not_called()
        copy.assert_called_once()
        back.assert_called_once()

    def test_text_fields_keep_normal_typing_and_do_not_trigger_filename_jumps(self):
        self.add_names(["alpha.png", "hello.png"])
        edit = self.window.filter_edit
        edit.setFocus()
        with patch.object(self.view, "jump_to_filename") as jump:
            QTest.keyClick(edit, Qt.Key.Key_H, Qt.KeyboardModifier.AltModifier)
            edit.clear()
            QTest.keyClicks(edit, "hello")
            jump.assert_not_called()
        self.assertEqual(edit.text(), "hello")

    def test_shift_letter_alternative_and_visible_folder_names(self):
        self.add_names(["alpha.png", "hello.png", "Holiday"])
        self.view.model().item(2).setData("folder", KIND_ROLE)
        QTest.keyClick(self.view, Qt.Key.Key_H, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.view.currentIndex().row(), 1)
        QTest.keyClick(self.view, Qt.Key.Key_H, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.view.currentIndex().row(), 2)

    def test_empty_view_and_missing_selection_are_handled(self):
        self.assertFalse(self.view.jump_to_filename("h"))
        self.add_names(["hello.png", "hotel.png"])
        self.view.selectionModel().clear()
        self.assertTrue(self.view.jump_to_filename("h"))
        self.assertEqual(self.view.currentIndex().row(), 0)


if __name__ == "__main__":
    unittest.main()
