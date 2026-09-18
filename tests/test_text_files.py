import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.thumbnail_view import KIND_ROLE, PATH_ROLE, ThumbnailView
from ui.transfer_conflicts import TransferJob, TransferConflictDialog, ResolvedTransfer, scan_transfer_job
from utils import file_ops


class TextFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config_patch.start()
        self.folder = os.path.join(self.temp.name, "source")
        self.destination = os.path.join(self.temp.name, "destination")
        os.mkdir(self.folder)
        os.mkdir(self.destination)
        self.image = os.path.join(self.folder, "a.png")
        self.caption = os.path.join(self.folder, "a.TXT")
        Image.new("RGB", (8, 6), "red").save(self.image)
        with open(self.caption, "w") as file:
            file.write("red image caption")
        self.window = MainWindow()
        self.app.processEvents()
        self.window.current_folder_path = self.folder
        self.window.thumbnail_view.load_folder(self.folder, show_folders=False)

    def tearDown(self):
        self.window.fullscreen_viewer.close()
        self.window.transfer_coordinator.shutdown()
        self.window.thumbnail_view.shutdown()
        self.window.crop_prefetch_service.shutdown()
        self.app.processEvents()
        self.window.close()
        self.config_patch.stop()
        self.temp.cleanup()

    def enable_text(self):
        self.window.show_text_action.setChecked(True)
        self.window.apply_pending_show_options()

    def select_both(self):
        self.window.select_image_by_path(self.image)
        view = self.window.thumbnail_view
        for path in (self.image, self.caption):
            index = view.model().indexFromItem(view.item_for_path(path))
            view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)

    def test_default_off_and_enabled_txt_is_not_decoded(self):
        view = self.window.thumbnail_view
        self.assertIsNone(view.item_for_path(self.caption))
        self.enable_text()
        self.assertEqual(view.item_for_path(self.caption).data(KIND_ROLE), "text")
        self.assertNotIn(self.caption, view.visible_image_paths())
        self.assertEqual([record[0] for record in view.files if record[4] == "image"], [self.image])
        self.assertFalse(view._icon_for_kind("text").isNull())
        fresh = ThumbnailView()
        self.assertFalse(fresh.show_text)
        fresh.close()

    def test_text_selection_clears_preview_and_activation_opens_externally(self):
        self.enable_text()
        self.window.select_image_by_path(self.image)
        self.window.select_image_by_path(self.caption)
        self.assertTrue(self.window.preview_viewer.pixmap_item.pixmap().isNull())
        with patch.object(self.window, "open_in_associated_program") as opened:
            self.window.open_current_thumbnail_fullscreen()
        opened.assert_called_once_with(self.caption)
        self.assertFalse(self.window.fullscreen_viewer.isVisible())

    def test_filter_sort_and_incremental_text_updates(self):
        self.enable_text()
        view = self.window.thumbnail_view
        view.set_filter_text(".txt")
        self.assertFalse(view.isRowHidden(view.item_for_path(self.caption).row()))
        self.assertTrue(view.isRowHidden(view.item_for_path(self.image).row()))
        added = os.path.join(self.folder, "b.txt")
        shutil.copyfile(self.caption, added)
        self.window.add_thumbnail_paths([added])
        self.assertEqual(view.item_for_path(added).data(KIND_ROLE), "text")
        renamed = os.path.join(self.folder, "c.txt")
        os.rename(added, renamed)
        self.window.update_renamed_thumbnail_item(view.item_for_path(added).row(), added, renamed)
        self.assertEqual(view.item_for_path(renamed).data(KIND_ROLE), "text")
        self.window.remove_thumbnail_paths([renamed])
        self.assertIsNone(view.item_for_path(renamed))
        self.window.load_current_folder()
        self.assertTrue(view.show_text)

    def test_mixed_selection_reaches_copy_move_and_clipboard(self):
        self.enable_text()
        self.select_both()
        self.assertEqual(self.window.selected_file_paths(), [self.image, self.caption])
        self.assertEqual(self.window.selected_image_paths(), [self.image])
        with patch("ui.main_window.CopyMoveDialog") as dialog, patch.object(self.window, "queue_transfer_files_to_folder") as queue:
            dialog.return_value.exec.return_value = True
            dialog.return_value.selected_folder = self.destination
            self.window.open_copy_dialog()
            self.assertEqual(queue.call_args.args[0], [self.image, self.caption])
            self.window.open_move_dialog()
            self.assertTrue(queue.call_args.kwargs["move_files"])
            self.assertEqual(queue.call_args.args[0], [self.image, self.caption])
        self.window.copy_to_clipboard()
        self.assertEqual([os.path.normpath(url.toLocalFile()) for url in QApplication.clipboard().mimeData().urls()], [self.image, self.caption])

    def test_text_conflict_uses_icon_and_existing_rename_resolution(self):
        self.enable_text()
        shutil.copyfile(self.caption, os.path.join(self.destination, "a.TXT"))
        plan = scan_transfer_job(TransferJob(1, [self.caption], self.destination))
        with patch("ui.transfer_conflicts.read_preview") as preview:
            dialog = TransferConflictDialog(plan)
        preview.assert_not_called()
        self.assertFalse(dialog.source_preview.pixmap().isNull())
        dialog._choose("rename")
        resolved = dialog.resolved_transfers()
        self.assertEqual(os.path.basename(resolved[0].target), "a-ren(1).TXT")
        dialog.close()

    def test_partial_mixed_move_removes_only_successful_file(self):
        self.enable_text()
        plan = scan_transfer_job(TransferJob(1, [self.image, self.caption], self.destination, move_files=True))
        resolved = [ResolvedTransfer(item.source, item.target) for item in plan.items]
        def move_one(pairs, **kwargs):
            shutil.move(*pairs[1])
            return None
        with patch("ui.main_window.move_file_pairs", side_effect=move_one):
            result = self.window.execute_queued_transfer(plan, resolved)
        self.assertEqual(result["successful_sources"], [self.caption])
        self.assertIsNone(self.window.thumbnail_view.item_for_path(self.caption))
        self.assertIsNotNone(self.window.thumbnail_view.item_for_path(self.image))

    def test_mixed_copy_writes_both_files_and_keeps_sources(self):
        self.enable_text()
        plan = scan_transfer_job(TransferJob(1, [self.image, self.caption], self.destination))
        resolved = [ResolvedTransfer(item.source, item.target) for item in plan.items]
        def copy_all(pairs, **kwargs):
            for source, target in pairs:
                shutil.copyfile(source, target)
            return True
        with patch("ui.main_window.copy_file_pairs", side_effect=copy_all):
            result = self.window.execute_queued_transfer(plan, resolved)
        self.assertEqual(result["successful_sources"], [self.image, self.caption])
        for path in (self.image, self.caption):
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(os.path.join(self.destination, os.path.basename(path))))

    def test_text_conflict_replace_skip_and_cancel(self):
        shutil.copyfile(self.caption, os.path.join(self.destination, "a.TXT"))
        plan = scan_transfer_job(TransferJob(1, [self.caption], self.destination))
        for decision in ("replace", "skip"):
            with self.subTest(decision=decision):
                dialog = TransferConflictDialog(plan)
                dialog._choose(decision)
                resolved = dialog.resolved_transfers()
                if decision == "replace":
                    self.assertTrue(resolved[0].replace)
                else:
                    self.assertEqual(resolved, [])
                dialog.close()
        with patch("ui.transfer_conflicts.TransferConflictDialog") as dialog, patch.object(self.window.transfer_coordinator, "execute_callback") as execute:
            dialog.return_value.exec.return_value = 0
            self.window.transfer_coordinator._process_plan(plan)
        execute.assert_not_called()
