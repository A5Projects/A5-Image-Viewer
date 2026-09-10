import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QEvent, QFileInfo, QItemSelectionModel, QMimeData, QPointF, QUrl, Qt
from PyQt6.QtGui import QShortcut, QStandardItem
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QHeaderView, QMessageBox, QTreeView

from ui.batch_operations import BatchRenameWorker
from ui.main_window import MainWindow
from ui.thumbnail_view import KIND_ROLE, PATH_ROLE


class MainWindowBatchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_batch_rename_updates_paths_cache_order_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            old_paths = []
            for name in ("b.png", "a.png"):
                path = os.path.join(folder, name)
                Image.new("RGB", (4, 4), "red").save(path)
                old_paths.append(path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    sort_key="name",
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )
                first_item = window.thumbnail_view.item_for_path(old_paths[0])
                first_index = window.thumbnail_view.model().indexFromItem(first_item)
                window.thumbnail_view.selectionModel().select(
                    first_index,
                    QItemSelectionModel.SelectionFlag.Select,
                )
                window.current_image_path = old_paths[0]
                window.current_item_kind = "image"
                window.thumbnail_view.thumbnail_cache[old_paths[0]] = (16, "image")
                window.thumbnail_view.thumbnail_cache[old_paths[1]] = (32, "image")
                window.thumbnail_view.thumbnail_cache_bytes = 48

                mapping = {
                    old_paths[0]: old_paths[1],
                    old_paths[1]: old_paths[0],
                }
                BatchRenameWorker(list(mapping.items())).run()
                window.apply_batch_rename_mapping(mapping, old_paths)

                self.assertEqual(
                    window.thumbnail_view.thumbnail_cache[mapping[old_paths[0]]],
                    (16, "image"),
                )
                self.assertEqual(
                    window.thumbnail_view.thumbnail_cache[mapping[old_paths[1]]],
                    (32, "image"),
                )
                self.assertEqual(window.thumbnail_view.thumbnail_cache_bytes, 48)
                model_names = [
                    os.path.basename(window.thumbnail_view.model().item(row).data(PATH_ROLE))
                    for row in range(window.thumbnail_view.model().rowCount())
                ]
                self.assertEqual(model_names, ["a.png", "b.png"])
                self.assertEqual(
                    set(window.selected_image_paths()),
                    set(mapping.values()),
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_rotate_left_action_and_shortcut_modify_current_image(self):
        with tempfile.TemporaryDirectory() as folder:
            image_path = os.path.join(folder, "image.png")
            Image.new("RGB", (6, 4), "red").save(image_path)
            window = MainWindow()
            try:
                window.current_image_path = image_path
                window.current_item_kind = "image"
                window.rotate_image_90_left()
                self.assertTrue(window.image_modified)
                self.assertEqual(
                    (window.modified_pixmap.width(), window.modified_pixmap.height()),
                    (4, 6),
                )
                shortcuts = {
                    shortcut.key().toString()
                    for shortcut in window.findChildren(QShortcut)
                }
                self.assertIn("L", shortcuts)
                self.assertTrue(any(
                    "Rotate 90 degrees left" in action.toolTip()
                    for action in window.toolbar.actions()
                ))
            finally:
                window.image_modified = False
                window.modified_pixmap = None
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_copy_and_move_use_ordered_multi_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            paths = []
            for name in ("a.png", "b.png", "c.png"):
                path = os.path.join(folder, name)
                Image.new("RGB", (4, 4), "red").save(path)
                paths.append(path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    sort_key="name",
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )
                selection = window.thumbnail_view.selectionModel()
                for path in (paths[0], paths[2]):
                    item = window.thumbnail_view.item_for_path(path)
                    index = window.thumbnail_view.model().indexFromItem(item)
                    selection.select(index, QItemSelectionModel.SelectionFlag.Select)
                window.current_image_path = paths[0]
                window.current_item_kind = "image"

                with (
                    patch("ui.main_window.CopyMoveDialog") as dialog_class,
                    patch.object(window, "queue_transfer_files_to_folder") as transfer,
                ):
                    dialog = dialog_class.return_value
                    dialog.exec.return_value = True
                    dialog.selected_folder = destination

                    window.open_copy_dialog()
                    transfer.assert_called_with(
                        [paths[0], paths[2]], destination, move_files=False
                    )

                    window.open_move_dialog()
                    transfer.assert_called_with(
                        [paths[0], paths[2]], destination, move_files=True,
                        context={
                            "fullscreen_source": None,
                            "fullscreen_target": None,
                        },
                    )

                window.fullscreen_viewer.set_current_image_path(paths[2])
                self.assertEqual(
                    window.file_operation_paths(window.fullscreen_viewer),
                    [paths[2]],
                )

                shortcuts = {
                    shortcut.key().toString(): shortcut
                    for shortcut in window.findChildren(QShortcut)
                }
                self.assertEqual(
                    shortcuts["C"].context(),
                    Qt.ShortcutContext.WindowShortcut,
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_fullscreen_navigation_stops_at_first_and_last_image(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name in ("a.png", "b.png", "c.png"):
                path = os.path.join(folder, name)
                Image.new("RGB", (4, 4), "red").save(path)
                paths.append(path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    sort_key="name",
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )

                with (
                    patch.object(window, "prompt_save_changes") as prompt,
                    patch.object(window, "load_prefetched_fullscreen") as load,
                ):
                    window.fullscreen_viewer.set_current_image_path(paths[-1])
                    window.current_image_path = paths[-1]
                    window.navigate_fullscreen(1)
                    prompt.assert_not_called()
                    load.assert_not_called()
                    self.assertEqual(window.current_image_path, paths[-1])

                    window.fullscreen_viewer.set_current_image_path(paths[0])
                    window.current_image_path = paths[0]
                    window.navigate_fullscreen(-1)
                    prompt.assert_not_called()
                    load.assert_not_called()
                    self.assertEqual(window.current_image_path, paths[0])
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_cancelled_copy_does_not_show_failure_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            source = os.path.join(folder, "image.png")
            Image.new("RGB", (4, 4), "red").save(source)

            window = MainWindow()
            try:
                with (
                    patch("ui.main_window.copy_files_batch", return_value=None),
                    patch.object(QMessageBox, "warning") as warning,
                ):
                    copied = window.transfer_files_to_folder(
                        [source], destination, move_files=False
                    )

                self.assertEqual(copied, [])
                warning.assert_not_called()
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_queued_conflict_can_auto_rename_without_native_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            source_folder = os.path.join(folder, "source")
            destination = os.path.join(folder, "destination")
            os.mkdir(source_folder)
            os.mkdir(destination)
            source = os.path.join(source_folder, "photo.png")
            existing = os.path.join(destination, "photo.png")
            Image.new("RGB", (4, 4), "red").save(source)
            Image.new("RGB", (4, 4), "blue").save(existing)

            window = MainWindow()
            finished = []
            window.transfer_coordinator.job_finished.connect(
                lambda job, result: finished.append(result)
            )
            exact_calls = []

            def choose_rename(dialog):
                dialog._choose("rename")
                return dialog.result()

            def copy_exact_pairs(pairs, overwrite=False, owner_hwnd=0):
                exact_calls.append((list(pairs), overwrite, owner_hwnd))
                for source_path, target_path in pairs:
                    shutil.copy2(source_path, target_path)
                return True

            try:
                with (
                    patch(
                        "ui.transfer_conflicts.TransferConflictDialog.exec",
                        new=choose_rename,
                    ),
                    patch(
                        "ui.main_window.copy_file_pairs",
                        side_effect=copy_exact_pairs,
                    ),
                ):
                    window.queue_transfer_files_to_folder(
                        [source], destination, move_files=False
                    )
                    deadline = time.monotonic() + 3.0
                    while not finished and time.monotonic() < deadline:
                        QTest.qWait(20)

                renamed = os.path.join(destination, "photo-ren(1).png")
                self.assertTrue(finished)
                self.assertEqual(len(exact_calls), 1)
                self.assertFalse(exact_calls[0][1])
                self.assertNotEqual(exact_calls[0][2], 0)
                self.assertTrue(os.path.isfile(renamed))
                self.assertTrue(os.path.isfile(existing))
                self.assertEqual(
                    finished[0]["copied_paths"],
                    [renamed],
                )
            finally:
                window.transfer_coordinator.shutdown()
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_folder_selection_is_written_to_file_clipboard(self):
        with tempfile.TemporaryDirectory() as folder:
            child = os.path.join(folder, "child")
            os.mkdir(child)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    show_images=False,
                    show_videos=False,
                    show_folders=True,
                )
                item = window.thumbnail_view.item_for_path(child)
                index = window.thumbnail_view.model().indexFromItem(item)
                window.thumbnail_view.setCurrentIndex(index)

                with patch.object(
                    QApplication, "focusWidget", return_value=window.thumbnail_view
                ):
                    window.copy_to_clipboard()

                paths = [
                    url.toLocalFile()
                    for url in QApplication.clipboard().mimeData().urls()
                ]
                self.assertEqual(
                    [os.path.normcase(os.path.normpath(path)) for path in paths],
                    [os.path.normcase(os.path.normpath(child))],
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_tree_folder_focus_takes_precedence_for_file_clipboard(self):
        with tempfile.TemporaryDirectory() as folder:
            child = os.path.join(folder, "tree-child")
            os.mkdir(child)

            window = MainWindow()
            try:
                index = window.file_model.index(child)
                window.tree_view.setCurrentIndex(index)

                with patch.object(
                    QApplication, "focusWidget", return_value=window.tree_view.viewport()
                ):
                    window.cut_to_clipboard()

                mime_data = QApplication.clipboard().mimeData()
                paths = [url.toLocalFile() for url in mime_data.urls()]
                self.assertEqual(
                    [os.path.normcase(os.path.normpath(path)) for path in paths],
                    [os.path.normcase(os.path.normpath(child))],
                )
                self.assertEqual(
                    bytes(mime_data.data("application/x-a5imageviewer-cut")),
                    b"1",
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_folder_from_system_clipboard_is_pasted_through_transfer_path(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source-folder")
            destination = os.path.join(folder, "destination")
            os.mkdir(source)
            os.mkdir(destination)

            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(source)])
            QApplication.clipboard().setMimeData(mime_data)

            window = MainWindow()
            try:
                window.current_folder_path = destination
                with patch.object(window, "transfer_files_to_folder") as transfer:
                    window.paste_from_clipboard()
                transfer.assert_called_once_with(
                    [QUrl.fromLocalFile(source).toLocalFile()],
                    destination,
                    move_files=False,
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_partial_multi_move_removes_only_successful_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            paths = []
            for name in ("first.png", "second.png"):
                path = os.path.join(folder, name)
                Image.new("RGB", (4, 4), "red").save(path)
                paths.append(path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )
                window.current_image_path = paths[0]
                window.current_item_kind = "image"

                def move_first(source_paths, destination_folder):
                    os.replace(
                        source_paths[0],
                        os.path.join(destination_folder, os.path.basename(source_paths[0])),
                    )
                    return True

                with (
                    patch("ui.main_window.move_files_batch", side_effect=move_first),
                    patch.object(QMessageBox, "warning"),
                ):
                    moved = window.transfer_files_to_folder(
                        paths, destination, move_files=True
                    )

                self.assertEqual(
                    moved,
                    [os.path.join(destination, os.path.basename(paths[0]))],
                )
                self.assertIsNone(window.thumbnail_view.item_for_path(paths[0]))
                self.assertIsNotNone(window.thumbnail_view.item_for_path(paths[1]))
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_adjust_board_handlers_move_selection_and_add_copy_incrementally(self):
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "first.png")
            second = os.path.join(folder, "second.png")
            output_copy = os.path.join(folder, "second_adj.png")
            for path in (first, second, output_copy):
                Image.new("RGB", (4, 4), "red").save(path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )
                window.current_image_path = first
                window.current_item_kind = "image"
                window.select_image_by_path(first, update_preview=False)

                with patch.object(window, "load_prefetched_preview") as preview_load:
                    window.on_adjust_board_image_changed(second)
                preview_load.assert_not_called()
                self.assertEqual(window.current_image_path, second)
                self.assertEqual(
                    window.thumbnail_view.currentIndex().data(PATH_ROLE), second
                )

                window.remove_thumbnail_paths([output_copy], keep_selection_path=second)
                self.assertIsNone(window.thumbnail_view.item_for_path(output_copy))
                window.on_adjust_board_image_saved(output_copy)

                self.assertIsNotNone(window.thumbnail_view.item_for_path(output_copy))
                self.assertEqual(window.current_image_path, second)
                self.assertEqual(
                    window.thumbnail_view.currentIndex().data(PATH_ROLE), second
                )
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_show_menu_batches_multiple_visibility_changes_until_close(self):
        window = MainWindow()
        try:
            window.current_folder_path = "P:/not-loaded-for-test"
            window.show_menu.show()
            QApplication.processEvents()
            self.assertTrue(window.show_menu.isVisible())

            with patch.object(window, "load_current_folder") as reload_folder:
                window.show_images_action.setChecked(False)
                window.show_videos_action.setChecked(True)
                QApplication.processEvents()
                reload_folder.assert_not_called()

                window.show_menu.hide()
                QTest.qWait(10)
                reload_folder.assert_called_once_with(keep_selection_path=None)
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_pdf_is_viewable_but_not_editable(self):
        self.assertFalse(MainWindow.is_editable_image_path("document.pdf"))
        self.assertTrue(MainWindow.is_editable_image_path("photo.webp"))

    def test_drive_strip_replaces_header_and_refreshes_available_drives(self):
        with patch(
            "ui.main_window.QDir.drives",
            return_value=[QFileInfo("C:/"), QFileInfo("P:/")],
        ):
            window = MainWindow()
        try:
            self.assertTrue(window.tree_view.isHeaderHidden())
            self.assertEqual(
                [button.text() for button in window.drive_buttons.values()],
                ["C", "P"],
            )

            with patch(
                "ui.main_window.QDir.drives",
                return_value=[QFileInfo("C:/"), QFileInfo("X:/")],
            ):
                window.refresh_drive_buttons()

            self.assertEqual(
                [button.text() for button in window.drive_buttons.values()],
                ["C", "X"],
            )
            with patch.object(window, "navigate_to_folder") as navigate:
                window.drive_buttons[window.drive_key_for_path("X:/")].click()
                navigate.assert_called_once_with("X:/")
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_drive_strip_does_not_limit_left_panel_width(self):
        drive_letters = "CDEFGHIJKLMNOPQRSTUVWXYZ"
        drive_infos = [QFileInfo(f"{letter}:/") for letter in drive_letters]
        with patch("ui.main_window.QDir.drives", return_value=drive_infos):
            window = MainWindow()
        try:
            window.resize(1200, 800)
            window.show()
            window.splitter_h.setSizes([175, 1025])
            QTest.qWait(30)

            visible_narrow = [
                button for button in window.drive_buttons.values()
                if not button.isHidden()
            ]
            self.assertLessEqual(window.splitter_h.sizes()[0], 210)
            self.assertGreater(len(visible_narrow), 0)
            self.assertLess(len(visible_narrow), len(drive_infos))
            self.assertFalse(next(iter(window.drive_buttons.values())).isHidden())
            self.assertTrue(list(window.drive_buttons.values())[-1].isHidden())
            for button in window.drive_buttons.values():
                self.assertLessEqual(
                    button.width(),
                    max(
                        16,
                        button.fontMetrics().horizontalAdvance(button.text()) + 7,
                    ),
                )

            window.splitter_h.setSizes([500, 700])
            QTest.qWait(30)
            visible_wide = [
                button for button in window.drive_buttons.values()
                if not button.isHidden()
            ]
            self.assertGreater(len(visible_wide), len(visible_narrow))
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_folder_tree_exposes_content_sized_horizontal_scrolling(self):
        window = MainWindow()
        try:
            self.assertEqual(
                window.tree_view.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            self.assertEqual(
                window.tree_view.horizontalScrollMode(),
                QTreeView.ScrollMode.ScrollPerPixel,
            )
            self.assertFalse(window.tree_view.header().stretchLastSection())
            self.assertEqual(
                window.tree_view.header().sectionResizeMode(0),
                QHeaderView.ResizeMode.ResizeToContents,
            )
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_drop_on_folder_thumbnail_uses_folder_as_transfer_destination(self):
        class DropEvent:
            def __init__(self, mime_data):
                self._mime_data = mime_data
                self.drop_action = None
                self.accepted = False

            def type(self):
                return QEvent.Type.Drop

            def mimeData(self):
                return self._mime_data

            def position(self):
                return QPointF(5, 5)

            def modifiers(self):
                return Qt.KeyboardModifier.NoModifier

            def setDropAction(self, action):
                self.drop_action = action

            def accept(self):
                self.accepted = True

        with tempfile.TemporaryDirectory() as folder:
            source_path = os.path.join(folder, "source.png")
            destination = os.path.join(folder, "destination")
            Image.new("RGB", (4, 4), "red").save(source_path)
            os.mkdir(destination)

            window = MainWindow()
            try:
                item = QStandardItem("destination")
                item.setData(destination, PATH_ROLE)
                item.setData("folder", KIND_ROLE)
                window.thumbnail_view.model().appendRow(item)
                index = window.thumbnail_view.model().indexFromItem(item)

                mime_data = QMimeData()
                mime_data.setUrls([QUrl.fromLocalFile(source_path)])
                event = DropEvent(mime_data)
                with (
                    patch.object(window.thumbnail_view, "indexAt", return_value=index),
                    patch.object(window, "transfer_files_to_folder") as transfer,
                ):
                    handled = window.eventFilter(
                        window.thumbnail_view.viewport(), event
                    )

                self.assertTrue(handled)
                self.assertTrue(event.accepted)
                self.assertEqual(event.drop_action, Qt.DropAction.MoveAction)
                transfer.assert_called_once()
                transferred_paths, transferred_folder = transfer.call_args.args
                self.assertEqual(
                    [os.path.normpath(path) for path in transferred_paths],
                    [os.path.normpath(source_path)],
                )
                self.assertEqual(os.path.normpath(transferred_folder), destination)
                self.assertTrue(transfer.call_args.kwargs["move_files"])
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()

    def test_forward_mouse_button_advances_folder_history(self):
        class MouseEvent:
            accepted = False

            def type(self):
                return QEvent.Type.MouseButtonPress

            def button(self):
                return Qt.MouseButton.ForwardButton

            def accept(self):
                self.accepted = True

        window = MainWindow()
        try:
            window.navigation_history = ["first", "second", "third"]
            window.navigation_index = 0
            with patch.object(window, "navigate_to_folder") as navigate:
                handled = window.eventFilter(
                    window.thumbnail_view.viewport(), MouseEvent()
                )
            self.assertTrue(handled)
            self.assertEqual(window.navigation_index, 1)
            navigate.assert_called_once_with("second", add_to_history=False)
        finally:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.close()

    def test_single_rename_uses_split_dialog_without_reloading_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path = os.path.join(folder, "old.name.png")
            new_path = os.path.join(folder, "new-name.webp")
            Image.new("RGB", (4, 4), "red").save(old_path)

            window = MainWindow()
            try:
                window.current_folder_path = folder
                window.thumbnail_view.load_folder(
                    folder,
                    show_images=True,
                    show_videos=False,
                    show_folders=False,
                )
                window.current_image_path = old_path
                window.current_item_kind = "image"

                with (
                    patch("ui.main_window.RenameDialog") as dialog_class,
                    patch.object(window, "load_current_folder") as reload_folder,
                ):
                    dialog_class.return_value.exec.return_value = 1
                    dialog_class.return_value.new_filename = "new-name.webp"
                    window.rename_file()

                self.assertFalse(os.path.exists(old_path))
                self.assertTrue(os.path.exists(new_path))
                self.assertIsNone(window.thumbnail_view.item_for_path(old_path))
                self.assertIsNotNone(window.thumbnail_view.item_for_path(new_path))
                reload_folder.assert_not_called()
            finally:
                window.thumbnail_view.shutdown()
                window.crop_prefetch_service.shutdown()
                window.close()


if __name__ == "__main__":
    unittest.main()
