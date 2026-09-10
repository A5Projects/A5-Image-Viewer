import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from PyQt6.QtGui import QImageReader

from utils import file_ops


class DeleteFilesTests(unittest.TestCase):
    def test_move_retries_sharing_violation_without_shell_error_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "locked.jpg")
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            Image.new("RGB", (64, 64), "red").save(source)
            holder = {"reader": QImageReader(source)}
            self.assertFalse(holder["reader"].read().isNull())

            release = threading.Timer(0.15, holder.clear)
            release.start()
            try:
                with patch.object(file_ops, "add_recent_folder"):
                    self.assertTrue(
                        file_ops._windows_file_op(
                            file_ops.FO_MOVE,
                            source,
                            destination,
                            timeout_seconds=2.0,
                        )
                    )
            finally:
                release.join()
                holder.clear()
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(os.path.join(destination, "locked.jpg")))

    def test_sharing_violation_is_retried_until_reader_releases_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "locked.jpg")
            Image.new("RGB", (64, 64), "red").save(path)
            holder = {"reader": QImageReader(path)}
            self.assertFalse(holder["reader"].read().isNull())

            release = threading.Timer(0.15, holder.clear)
            release.start()
            try:
                self.assertTrue(
                    file_ops.delete_files([path], permanent=True, timeout_seconds=2.0)
                )
            finally:
                release.join()
                holder.clear()
            self.assertFalse(os.path.exists(path))

    def test_non_sharing_shell_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "image.jpg")
            Image.new("RGB", (2, 2), "red").save(path)
            shell_operation = patch.object(
                file_ops.ctypes.windll.shell32,
                "SHFileOperationW",
                return_value=5,
            )
            with shell_operation as operation:
                self.assertFalse(file_ops.delete_files([path], permanent=True))
            operation.assert_called_once()

    def test_cancelled_shell_copy_is_reported_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "image.jpg")
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            Image.new("RGB", (2, 2), "red").save(source)

            def cancel(operation_pointer):
                operation = file_ops.ctypes.cast(
                    operation_pointer,
                    file_ops.ctypes.POINTER(file_ops.SHFILEOPSTRUCTW),
                ).contents
                operation.fAnyOperationsAborted = True
                return 0

            with patch.object(
                file_ops.ctypes.windll.shell32,
                "SHFileOperationW",
                side_effect=cancel,
            ):
                self.assertIsNone(
                    file_ops._windows_file_op(
                        file_ops.FO_COPY,
                        source,
                        destination,
                    )
                )

    def test_multi_copy_is_submitted_as_one_shell_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "destination")
            os.mkdir(destination)
            sources = []
            for name in ("first.jpg", "second.jpg", "third.jpg"):
                path = os.path.join(folder, name)
                Image.new("RGB", (2, 2), "red").save(path)
                sources.append(os.path.abspath(path))

            expected_payload = "\0".join(sources) + "\0\0"
            captured_sources = []

            def capture(operation_pointer):
                operation = file_ops.ctypes.cast(
                    operation_pointer,
                    file_ops.ctypes.POINTER(file_ops.SHFILEOPSTRUCTW),
                ).contents
                captured_sources.extend(
                    file_ops.ctypes.wstring_at(
                        operation.pFrom, len(expected_payload)
                    ).split("\0")[:-2]
                )
                return 0

            with (
                patch.object(file_ops, "add_recent_folder"),
                patch.object(
                    file_ops.ctypes.windll.shell32,
                    "SHFileOperationW",
                    side_effect=capture,
                ) as operation,
            ):
                self.assertTrue(file_ops.copy_files(sources, destination))

            operation.assert_called_once()
            self.assertEqual(captured_sources, sources)


if __name__ == "__main__":
    unittest.main()
