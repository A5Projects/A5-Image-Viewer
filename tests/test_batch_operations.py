import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ui.batch_operations import (
    BatchRenameWorker,
    build_batch_rename_plan,
    parse_rename_template,
    rename_with_sharing_retry,
    render_rename_template,
    transform_image_atomic,
)


class RenameTemplateTests(unittest.TestCase):
    def test_template_rendering_and_overflow(self):
        tokens, width = parse_rename_template("X-####_flying")
        self.assertEqual(width, 4)
        self.assertEqual(render_rename_template(tokens, "original", 15), "X-0015_flying")
        self.assertEqual(render_rename_template(tokens, "original", 12345), "X-12345_flying")

    def test_original_name_and_escaped_hash(self):
        tokens, width = parse_rename_template(r"*\###")
        self.assertEqual(width, 2)
        self.assertEqual(render_rename_template(tokens, "photo", 3), "photo#03")

    def test_multiple_number_runs_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_rename_template("##-##")

    def test_plan_preserves_extensions_and_detects_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "one.jpg")
            second = os.path.join(folder, "two.png")
            collision = os.path.join(folder, "image01.jpg")
            for path in (first, second, collision):
                Image.new("RGB", (2, 2), "red").save(path)

            plan, errors, has_number = build_batch_rename_plan(
                [first, second],
                "image##",
                1,
            )
            self.assertTrue(has_number)
            self.assertEqual(os.path.splitext(plan[1][1])[1], ".png")
            self.assertTrue(errors)

    def test_plan_allows_selected_name_swaps(self):
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "01.jpg")
            second = os.path.join(folder, "02.jpg")
            for path in (first, second):
                Image.new("RGB", (2, 2), "red").save(path)

            plan, errors, _ = build_batch_rename_plan([first, second], "##", 2)
            self.assertFalse(errors)
            self.assertEqual(os.path.basename(plan[0][1]), "02.jpg")


class BatchRenameWorkerTests(unittest.TestCase):
    def test_sharing_violation_is_retried(self):
        attempts = []

        def temporarily_locked(source, destination):
            attempts.append((source, destination))
            if len(attempts) < 3:
                error = OSError("file is in use")
                error.winerror = 32
                raise error

        with patch("ui.batch_operations.os.rename", side_effect=temporarily_locked):
            rename_with_sharing_retry("old", "new", timeout_seconds=1.0)

        self.assertEqual(len(attempts), 3)

    def test_non_sharing_error_is_not_retried(self):
        error = PermissionError("access denied")
        error.winerror = 5
        with patch("ui.batch_operations.os.rename", side_effect=error) as rename:
            with self.assertRaises(PermissionError):
                rename_with_sharing_retry("old", "new", timeout_seconds=1.0)
        rename.assert_called_once()

    def test_two_phase_rename_supports_swaps(self):
        with tempfile.TemporaryDirectory() as folder:
            first = os.path.join(folder, "first.jpg")
            second = os.path.join(folder, "second.jpg")
            with open(first, "wb") as handle:
                handle.write(b"first")
            with open(second, "wb") as handle:
                handle.write(b"second")

            worker = BatchRenameWorker([(first, second), (second, first)])
            worker.run()

            with open(first, "rb") as handle:
                self.assertEqual(handle.read(), b"second")
            with open(second, "rb") as handle:
                self.assertEqual(handle.read(), b"first")
            self.assertFalse(any(name.startswith(".a5rename-") for name in os.listdir(folder)))

    def test_case_only_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path = os.path.join(folder, "photo.jpg")
            new_path = os.path.join(folder, "PHOTO.jpg")
            with open(old_path, "wb") as handle:
                handle.write(b"image")

            BatchRenameWorker([(old_path, new_path)]).run()
            self.assertTrue(os.path.exists(new_path))


class BatchTransformTests(unittest.TestCase):
    def make_image(self, folder, name="source.png"):
        path = os.path.join(folder, name)
        image = Image.new("RGB", (3, 2))
        image.putdata([
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 0, 255),
            (0, 255, 255),
        ])
        image.save(path)
        return path

    def test_all_transform_operations(self):
        expected_sizes = {
            "right": (2, 3),
            "left": (2, 3),
            "180": (3, 2),
            "flip_h": (3, 2),
            "flip_v": (3, 2),
        }
        for operation, expected_size in expected_sizes.items():
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                path = self.make_image(folder)
                transform_image_atomic(path, operation)
                with Image.open(path) as result:
                    self.assertEqual(result.size, expected_size)
                self.assertFalse(any(name.startswith(".a5rotate-") for name in os.listdir(folder)))

    def test_exif_orientation_is_normalized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_image(folder, "source.jpg")
            with Image.open(path) as image:
                exif = image.getexif()
                exif[274] = 6
                image.save(path, exif=exif)

            transform_image_atomic(path, "flip_h")
            with Image.open(path) as result:
                self.assertEqual(result.getexif().get(274), 1)

    def test_animated_image_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "animated.gif")
            frames = [Image.new("RGB", (2, 2), color) for color in ("red", "blue")]
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0)
            with open(path, "rb") as handle:
                before = handle.read()

            with self.assertRaises(ValueError):
                transform_image_atomic(path, "right")

            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
            self.assertFalse(any(name.startswith(".a5rotate-") for name in os.listdir(folder)))


if __name__ == "__main__":
    unittest.main()
