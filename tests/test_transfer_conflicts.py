import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from ui.transfer_conflicts import (
    TransferConflictDialog,
    TransferCoordinator,
    TransferJob,
    recommended_rename_target,
    scan_transfer_job,
)


class TransferConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_folder = os.path.join(self.temp_dir.name, "source")
        self.destination = os.path.join(self.temp_dir.name, "destination")
        os.mkdir(self.source_folder)
        os.mkdir(self.destination)

    def tearDown(self):
        self.temp_dir.cleanup()

    def image(self, folder, name, color="red"):
        path = os.path.join(folder, name)
        Image.new("RGB", (12, 8), color).save(path)
        return path

    def conflict_plan(self, names):
        sources = []
        for index, name in enumerate(names):
            sources.append(self.image(self.source_folder, name, "red"))
            self.image(self.destination, name, "blue")
        return scan_transfer_job(TransferJob(1, sources, self.destination))

    @staticmethod
    def key_event(letter):
        return QKeyEvent(
            QEvent.Type.KeyPress,
            getattr(Qt.Key, f"Key_{letter.upper()}"),
            Qt.KeyboardModifier.NoModifier,
            letter.lower(),
        )

    def test_recommended_name_increments_existing_and_extended_names(self):
        source = self.image(self.source_folder, "photo.jpg")
        self.image(self.destination, "photo.jpg")
        self.image(self.destination, "photo-ren(1).jpg")
        self.assertEqual(
            os.path.basename(recommended_rename_target(source, self.destination)),
            "photo-ren(2).jpg",
        )

        extended = self.image(self.source_folder, "other-ren(4).jpg")
        self.image(self.destination, "other-ren(4).jpg")
        self.assertEqual(
            os.path.basename(recommended_rename_target(extended, self.destination)),
            "other-ren(5).jpg",
        )

    def test_scan_builds_conflicts_without_enumerating_destination(self):
        with patch(
            "ui.transfer_conflicts.os.scandir",
            side_effect=AssertionError("destination enumeration is not allowed"),
        ):
            plan = self.conflict_plan(["one.jpg", "two.jpg"])

        self.assertFalse(plan.error_code)
        self.assertEqual(len(plan.items), 2)
        self.assertTrue(all(item.conflict for item in plan.items))
        self.assertEqual(
            [os.path.basename(item.rename_target) for item in plan.items],
            ["one-ren(1).jpg", "two-ren(1).jpg"],
        )

    def test_plain_shortcuts_trigger_every_conflict_action(self):
        expectations = {
            "r": (1, True, "photo.jpg"),
            "a": (1, True, "photo.jpg"),
            "s": (0, None, None),
            "l": (0, None, None),
            "n": (1, False, "photo-ren(1).jpg"),
            "m": (1, False, "photo-ren(1).jpg"),
        }
        for key, expected in expectations.items():
            with self.subTest(key=key):
                plan = self.conflict_plan(["photo.jpg"])
                dialog = TransferConflictDialog(plan)
                dialog.keyPressEvent(self.key_event(key))
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                resolved = dialog.resolved_transfers()
                self.assertEqual(len(resolved), expected[0])
                if resolved:
                    self.assertEqual(resolved[0].replace, expected[1])
                    self.assertEqual(os.path.basename(resolved[0].target), expected[2])
                dialog.close()
                os.remove(os.path.join(self.source_folder, "photo.jpg"))
                os.remove(os.path.join(self.destination, "photo.jpg"))

        cancel_plan = self.conflict_plan(["cancel.jpg"])
        cancel_dialog = TransferConflictDialog(cancel_plan)
        cancel_dialog.keyPressEvent(self.key_event("c"))
        self.assertEqual(cancel_dialog.result(), QDialog.DialogCode.Rejected)
        cancel_dialog.close()

    def test_rename_all_uses_unique_precomputed_targets(self):
        plan = self.conflict_plan(["one.jpg", "two.jpg"])
        dialog = TransferConflictDialog(plan)

        dialog.keyPressEvent(self.key_event("m"))

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(
            [os.path.basename(item.target) for item in dialog.resolved_transfers()],
            ["one-ren(1).jpg", "two-ren(1).jpg"],
        )
        dialog.close()

    def test_conflict_dialog_is_application_modal_and_owned(self):
        plan = self.conflict_plan(["owned.jpg"])
        owner = QWidget()
        dialog = TransferConflictDialog(plan, owner)

        self.assertIs(dialog.parent(), owner)
        self.assertEqual(
            dialog.windowModality(),
            Qt.WindowModality.ApplicationModal,
        )

        dialog.close()
        owner.close()

    def test_preflight_does_not_block_gui_caller(self):
        source = self.image(self.source_folder, "image.jpg")
        owner = QWidget()
        executor = MagicMock(return_value={"successful_sources": [source]})
        coordinator = TransferCoordinator(lambda: owner, executor, max_scans=1)
        finished = []
        coordinator.job_finished.connect(lambda job, result: finished.append(result))

        original_scan = coordinator._scan_in_background

        def delayed_scan(job):
            time.sleep(0.15)
            original_scan(job)

        coordinator._scan_in_background = delayed_scan
        started = time.perf_counter()
        coordinator.enqueue([source], self.destination)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.08)
        deadline = time.monotonic() + 2.0
        while not finished and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(finished)
        executor.assert_called_once()
        coordinator.shutdown()
        owner.close()


if __name__ == "__main__":
    unittest.main()
