import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from ui.convert_dialog import ConvertWorker


class AnimatedConversionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.output = self.folder / "converted"
        self.output.mkdir()

    def animation(self, name, loop=None):
        path = self.folder / name
        frames = []
        for x, color in ((2, "red"), (11, "green"), (20, "blue")):
            frame = Image.new("RGBA", (32, 16))
            ImageDraw.Draw(frame).rectangle((x, 3, x + 8, 12), fill=color)
            frames.append(frame)
        options = {} if loop is None else {"loop": loop}
        if path.suffix == ".gif":
            options["disposal"] = 2
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=[60, 130, 210], **options)
        return path

    def convert(self, path, *, fmt="WebP", rotate=None, in_place=False, keep_date=False,
                delete=True, expect_success=True):
        worker = ConvertWorker([str(path)], None if in_place else str(self.output), "",
                               fmt, rotate, 90, keep_date, delete)
        errors = []
        completed = []
        worker.error.connect(lambda file, message: errors.append((file, message)))
        worker.finished.connect(lambda count, total: completed.append((count, total)))
        worker.run()
        self.assertEqual(completed, [(int(expect_success), 1)], errors)
        if expect_success:
            self.assertEqual(errors, [])
        else:
            self.assertEqual([file for file, _ in errors], [str(path)])
            self.assertEqual(worker.changed_paths, [])
        return errors

    def test_gif_to_webp_rotates_every_frame_and_preserves_delays_transparency_and_repetitions(self):
        source = self.animation("example.gif", loop=2)
        expected = []
        with Image.open(source) as gif:
            for i in range(gif.n_frames):
                gif.seek(i)
                expected.append(gif.convert("RGBA").transpose(Image.Transpose.ROTATE_270))
        self.convert(source, rotate="right")
        self.assertFalse(source.exists())
        with Image.open(self.output / "example.webp") as output:
            self.assertEqual((output.n_frames, output.size, output.info["loop"]), (3, (16, 32), 3))
            for index, duration in enumerate((60, 130, 210)):
                output.seek(index)
                actual = output.convert("RGBA")
                self.assertEqual(output.info["duration"], duration)
                self.assertEqual(actual.getchannel("A").tobytes(), expected[index].getchannel("A").tobytes())
                point = (8, (6, 15, 24)[index])
                for observed, original in zip(actual.getpixel(point), expected[index].getpixel(point)):
                    self.assertAlmostEqual(observed, original, delta=12)

    def test_gif_with_no_loop_extension_plays_once_and_zero_repeats_forever(self):
        for index, (gif_loop, webp_plays) in enumerate(((None, 1), (0, 0))):
            with self.subTest(gif_loop=gif_loop):
                source = self.animation(f"loop-{index}.gif", loop=gif_loop)
                self.convert(source, delete=False)
                with Image.open(self.output / f"loop-{index}.webp") as output:
                    self.assertEqual(output.n_frames, 3)
                    self.assertEqual(output.info["loop"], webp_plays)
                self.assertTrue(source.exists())

    def test_single_frame_gif_keeps_its_transparent_palette_entry(self):
        source = self.folder / "still.gif"
        image = Image.new("P", (6, 3))
        image.putpalette([0, 0, 0, 255, 0, 0])
        image.paste(1, (3, 0, 6, 3))
        image.save(source, transparency=0)
        self.convert(source)
        with Image.open(self.output / "still.webp") as output:
            rgba = output.convert("RGBA")
            self.assertEqual(rgba.getpixel((1, 1))[3], 0)
            self.assertEqual(rgba.getpixel((4, 1))[3], 255)

    def test_size_limit_skips_oversized_png_in_plain_and_comfy_conversion(self):
        large = self.folder / "large.png"
        Image.new("RGB", (640, 512), "red").save(large)
        original = large.read_bytes()
        target = self.output / "large.webp"
        target.write_bytes(b"previous result")
        for keep_comfy in (False, True):
            with self.subTest(keep_comfy=keep_comfy):
                small = self.folder / "small.png"
                Image.new("RGB", (8, 8), "blue").save(small)
                with patch("ui.convert_dialog.get_image_settings", return_value={"max_decoded_image_mb": 1}):
                    worker = ConvertWorker([str(large), str(small)], str(self.output), "", "WebP",
                                           None, 90, False, True, keep_comfy)
                errors = []
                worker.error.connect(lambda path, message: errors.append((path, message)))
                worker.run()
                self.assertEqual([path for path, _ in errors], [str(large)])
                self.assertIn("1 MiB", errors[0][1])
                self.assertEqual(large.read_bytes(), original)
                self.assertEqual(target.read_bytes(), b"previous result")
                self.assertFalse(small.exists())
                with Image.open(self.output / "small.webp") as result:
                    self.assertEqual(result.size, (8, 8))

    def test_animation_respects_frame_and_accumulated_transform_limits(self):
        source = self.folder / "many.gif"
        for size, rotate, message in (((640, 512), None, "1 MiB"),
                                      ((400, 400), "right", "Rotating or flipping")):
            with self.subTest(size=size):
                Image.new("RGB", size, "red").save(
                    source, save_all=True, append_images=[Image.new("RGB", size, "blue")],
                    loop=0, duration=100,
                )
                before = source.read_bytes()
                with patch("ui.convert_dialog.get_image_settings", return_value={"max_decoded_image_mb": 1}):
                    errors = self.convert(source, rotate=rotate, expect_success=False)
                self.assertIn(message, errors[0][1])
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_animated_webp_can_be_flipped_in_place_with_keep_date_and_delete_original(self):
        source = self.animation("original.webp", loop=4)
        stamp = 1_700_000_000_000_000_000
        os.utime(source, ns=(stamp, stamp))
        self.convert(source, fmt=None, rotate="flip_h", in_place=True, keep_date=True)
        self.assertEqual(source.stat().st_mtime_ns, stamp)
        with Image.open(source) as output:
            self.assertEqual((output.n_frames, output.info["loop"]), (3, 4))
            self.assertEqual(output.convert("RGBA").getpixel((25, 8))[3], 255)
            self.assertEqual(output.convert("RGBA").getpixel((6, 8))[3], 0)
        self.assertCountEqual(self.folder.iterdir(), [source, self.output])

    def test_unsupported_outputs_preserve_all_original_pages_and_the_existing_destination(self):
        source = self.animation("protected.gif")
        existing = self.output / "protected.jpeg"
        Image.new("RGB", (3, 5), "gold").save(existing)
        contents = {path: path.read_bytes() for path in (source, existing)}
        self.convert(source, fmt="JPEG", expect_success=False)
        self.convert(source, fmt=None, in_place=True, rotate="left", expect_success=False)
        self.assertEqual({path: path.read_bytes() for path in contents}, contents)

        pages = self.folder / "pages.tiff"
        Image.new("RGB", (4, 5), "red").save(
            pages, save_all=True, append_images=[Image.new("RGB", (8, 2), "blue")]
        )
        before = pages.read_bytes()
        self.convert(pages, expect_success=False)
        self.assertEqual(pages.read_bytes(), before)
        self.assertEqual(list(self.output.iterdir()), [existing])

    def test_an_encoder_that_changes_frame_delays_cannot_replace_or_delete_files(self):
        source = self.animation("existing.gif")
        target = self.output / "existing.webp"
        Image.new("RGB", (2, 3), "purple").save(target)
        before = {path: path.read_bytes() for path in (source, target)}
        save = Image.Image.save

        def write_wrong_timing(frame, destination, format=None, **options):
            options["duration"] = 100
            return save(frame, destination, format, **options)

        with patch.object(Image.Image, "save", write_wrong_timing):
            errors = self.convert(source, expect_success=False)
        self.assertIn("timing", errors[0][1].lower())
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(list(self.output.iterdir()), [target])

    def test_invalid_static_encode_is_discarded_before_in_place_overwrite(self):
        source = self.folder / "safe.png"
        Image.new("RGB", (11, 7), "navy").save(source)
        before = source.read_bytes()

        def write_invalid_image(frame, destination, **options):
            Path(destination).write_bytes(b"incomplete image")

        with patch.object(Image.Image, "save", write_invalid_image):
            self.convert(source, fmt=None, in_place=True, rotate="right", expect_success=False)
        self.assertEqual(source.read_bytes(), before)
        self.assertCountEqual(self.folder.iterdir(), [source, self.output])


if __name__ == "__main__":
    unittest.main()
