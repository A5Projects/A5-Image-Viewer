import json
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, PngImagePlugin
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.convert_dialog import ConvertDialog, ConvertWorker
from utils import file_ops


class ComfyConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "output"
        self.output.mkdir()
        config = patch.object(file_ops, "CONFIG_FILE", str(self.root / "config.json"))
        config.start()
        self.addCleanup(config.stop)

        self.positive = "Crème brûlée, 夜空 🌌"
        self.negative = "motion blur"
        self.prompt = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": self.positive}},
            "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative"},
                  "inputs": {"text": self.negative}},
            "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "night.safetensors"}},
            "4": {"class_type": "KSampler", "inputs": {
                "positive": ["1", 0], "negative": ["2", 0], "seed": 327, "steps": 15,
                "cfg": 5.5, "sampler_name": "euler", "scheduler": "normal", "denoise": 0.8,
            }},
        }
        self.workflow = {"version": 0.4, "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "widgets_values": [self.positive]},
            {"id": 2, "type": "CLIPTextEncode", "title": "Negative",
             "widgets_values": [self.negative]},
        ]}

    def make_png(self, name, metadata, **save_options):
        source = self.root / name
        chunks = PngImagePlugin.PngInfo()
        for key, value in metadata.items():
            if key == "prompt":
                chunks.add_text(key, json.dumps(value))
            else:
                chunks.add_itxt(key, json.dumps(value, ensure_ascii=False), zip=True)
        Image.new("RGBA", (18, 9), (68, 102, 136, 128)).save(source, pnginfo=chunks, **save_options)
        return source

    def convert(self, sources, *, successes=None, delete=False, rotate=None, keep_date=False, **options):
        worker = ConvertWorker([str(path) for path in sources], str(self.output), "", "WebP",
                               rotate, 90, keep_date, delete, **options)
        errors = []
        totals = []
        worker.error.connect(lambda path, message: errors.append((path, message)))
        worker.finished.connect(lambda count, total: totals.append((count, total)))
        worker.run()
        if successes is None:
            self.assertEqual(errors, [])
            successes = len(sources)
        self.assertEqual(totals, [(successes, len(sources))], errors)
        return worker, errors

    def assert_native_graph(self, exif, tag, key, expected):
        value = exif.get(tag)
        self.assertIsInstance(value, str)
        prefix, separator, text = value.partition(":")
        self.assertEqual((prefix, separator), (key, ":"))
        self.assertEqual(json.loads(text), expected)

    def test_full_graph_and_compact_summary_survive_unicode_and_large_metadata(self):
        self.workflow["extra"] = {"annotation": "workflow notes: " + "a" * 70_000 + " 🌠"}
        artist = Image.Exif()
        artist[0x013B] = "A5"
        source = self.make_png("night.PNG", {"prompt": self.prompt, "workflow": self.workflow}, exif=artist)
        stamp = 1_700_000_000_000_000_000
        os.utime(source, ns=(stamp, stamp))
        self.convert([source], keep_comfy=True, delete=True, rotate="right", keep_date=True)

        target = self.output / "night.webp"
        self.assertFalse(source.exists())
        self.assertEqual(target.stat().st_mtime_ns, stamp)
        self.assertEqual(list(self.output.iterdir()), [target])
        with Image.open(target) as image:
            image.load()
            self.assertEqual((image.format, image.size), ("WEBP", (9, 18)))
            self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 128)
            exif = image.getexif()
            self.assert_native_graph(exif, 0x0110, "prompt", self.prompt)
            self.assert_native_graph(exif, 0x010F, "workflow", self.workflow)
            self.assertEqual(exif.get(0x013B), "A5")
            summary = json.loads(image.info["xmp"].decode("utf-8"))
            for key, expected in {
                "source_format": "ComfyUI compact", "positive_prompt": self.positive,
                "negative_prompt": self.negative, "model": "night.safetensors", "seed": 327,
                "steps": 15, "cfg_scale": 5.5, "sampler": "euler", "scheduler": "normal",
                "denoise": 0.8,
            }.items():
                with self.subTest(field=key):
                    self.assertEqual(summary.get(key), expected)
            self.assertEqual(json.loads(exif[0x010E]), summary)
            comment = exif[0x9286]
            self.assertTrue(comment.startswith(b"UTF8\0\0\0"))
            self.assertEqual(json.loads(comment[7:].decode("utf-8")), summary)

    def test_prompt_and_workflow_can_each_be_preserved_independently(self):
        for key, value, tag, missing_tag in (
            ("prompt", self.prompt, 0x0110, 0x010F),
            ("workflow", self.workflow, 0x010F, 0x0110),
        ):
            with self.subTest(key=key):
                source = self.make_png(f"{key}.png", {key: value})
                self.convert([source], keep_comfy=True)
                with Image.open(self.output / f"{key}.webp") as image:
                    exif = image.getexif()
                    self.assert_native_graph(exif, tag, key, value)
                    self.assertNotIn(missing_tag, exif)
                    self.assertEqual(json.loads(image.info["xmp"])["positive_prompt"], self.positive)

    def test_opt_out_keeps_ordinary_exif_and_omits_comfy_metadata(self):
        artist = Image.Exif()
        artist[0x013B] = "Camera artist"
        source = self.make_png("image.png", {"prompt": self.prompt, "workflow": self.workflow}, exif=artist)
        for options in ({}, {"keep_comfy": False}):
            with self.subTest(options=options):
                self.convert([source], **options)
                with Image.open(self.output / "image.webp") as image:
                    exif = image.getexif()
                    self.assertEqual(exif.get(0x013B), "Camera artist")
                    self.assertNotIn(0x0110, exif)
                    self.assertNotIn(0x010F, exif)
                    self.assertNotIn("xmp", image.info)

    def test_plain_static_png_does_not_gain_a_synthetic_workflow(self):
        source = self.make_png("plain.png", {})
        self.convert([source], keep_comfy=True)
        with Image.open(self.output / "plain.webp") as image:
            image.load()
            self.assertEqual(image.size, (18, 9))
            self.assertNotIn(0x0110, image.getexif())
            self.assertNotIn(0x010F, image.getexif())
            self.assertNotIn("xmp", image.info)

    def test_verification_failure_leaves_source_and_previous_output_intact(self):
        source = self.make_png("existing.png", {"prompt": self.prompt, "workflow": self.workflow})
        target = self.output / "existing.webp"
        Image.new("RGB", (3, 5), "blue").save(target)
        source_before = source.read_bytes()
        target_before = target.read_bytes()
        save = Image.Image.save

        for corruption in ("missing EXIF", "missing XMP", "changed compact seed"):
            with self.subTest(corruption=corruption):
                encoded = []

                def encode_incorrect_metadata(image, fp, format=None, **params):
                    if str(format).upper() == "WEBP":
                        if corruption == "changed compact seed":
                            summary = json.loads(params["xmp"])
                            summary["seed"] += 1
                            params["xmp"] = json.dumps(summary).encode("utf-8")
                        else:
                            params["exif" if corruption == "missing EXIF" else "xmp"] = b""
                    result = save(image, fp, format, **params)
                    encoded.append(format)
                    return result

                with patch.object(Image.Image, "save", encode_incorrect_metadata):
                    worker, errors = self.convert([source], keep_comfy=True, delete=True, successes=0)
                self.assertEqual([str(fmt).upper() for fmt in encoded], ["WEBP"])
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0][0], str(source))
                self.assertTrue(errors[0][1])
                self.assertEqual(worker.changed_paths, [])
                self.assertEqual(source.read_bytes(), source_before)
                self.assertEqual(target.read_bytes(), target_before)
                self.assertEqual(list(self.output.iterdir()), [target])

    def test_graph_json_with_nonfinite_numbers_keeps_originals_and_previous_outputs(self):
        sources = []
        previous_outputs = {}
        originals = {}
        for graph, number in (("prompt", "NaN"), ("workflow", "Infinity")):
            source = self.root / f"{graph}.png"
            chunks = PngImagePlugin.PngInfo()
            chunks.add_text(graph, '{"value":' + number + '}')
            Image.new("RGB", (9, 8), "red").save(source, pnginfo=chunks)
            target = self.output / f"{graph}.webp"
            Image.new("RGB", (3, 5), "blue").save(target)
            sources.append(source)
            originals[source] = source.read_bytes()
            previous_outputs[target] = target.read_bytes()
        worker, errors = self.convert(sources, keep_comfy=True, delete=True, successes=0)
        self.assertCountEqual([path for path, _ in errors], map(str, sources))
        self.assertEqual(worker.changed_paths, [])
        self.assertEqual({path: path.read_bytes() for path in sources}, originals)
        self.assertEqual({path: path.read_bytes() for path in self.output.iterdir()}, previous_outputs)

    def test_mixed_batch_skips_apng_and_preserves_existing_static_jpeg_and_webp_metadata(self):
        frames = [Image.new("RGBA", (18, 9), color) for color in ("red", "blue")]
        animation = self.root / "animated.png"
        frames[0].save(animation, save_all=True, append_images=frames[1:], duration=50, loop=0)
        ordinary = self.root / "ordinary.jpg"
        artist = Image.Exif()
        artist[0x013B] = "Camera artist"
        xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
        Image.new("RGB", (7, 4), "green").save(ordinary, exif=artist, xmp=xmp)
        previous = self.root / "previous.webp"
        graph = Image.Exif()
        graph[0x0110] = "prompt:" + json.dumps(self.prompt)
        compact = json.dumps({"source_format": "ComfyUI compact", "positive_prompt": self.positive}).encode()
        Image.new("RGB", (11, 3), "red").save(previous, exif=graph, xmp=compact)
        before = animation.read_bytes()
        _, errors = self.convert([animation, ordinary, previous], keep_comfy=True, delete=True, successes=2)

        self.assertEqual([path for path, _ in errors], [str(animation)])
        self.assertEqual(animation.read_bytes(), before)
        self.assertFalse(ordinary.exists())
        self.assertFalse(previous.exists())
        target = self.output / "ordinary.webp"
        native = self.output / "previous.webp"
        self.assertCountEqual(self.output.iterdir(), [target, native])
        with Image.open(target) as image:
            image.load()
            self.assertEqual(image.size, (7, 4))
            self.assertEqual(image.getexif().get(0x013B), "Camera artist")
            self.assertNotIn(0x0110, image.getexif())
            self.assertEqual(image.info.get("xmp"), xmp)
        with Image.open(native) as image:
            self.assert_native_graph(image.getexif(), 0x0110, "prompt", self.prompt)
            self.assertEqual(image.info.get("xmp"), compact)

    def test_dialog_offers_an_unchecked_webp_option_and_passes_it_to_the_worker(self):
        source = self.make_png("from-dialog.png", {"prompt": self.prompt})
        dialog = ConvertDialog([str(source)])
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        for name in ("PNG", "JPEG", "Don't change"):
            dialog.format_combo.setCurrentText(name)
            self.assertFalse(dialog.keep_comfy_cb.isVisible() and dialog.keep_comfy_cb.isEnabled())
        dialog.format_combo.setCurrentText("WebP")
        self.assertTrue(dialog.keep_comfy_cb.isVisible() and dialog.keep_comfy_cb.isEnabled())
        self.assertFalse(dialog.keep_comfy_cb.isChecked())
        dialog.keep_comfy_cb.setChecked(True)
        dialog.radio_custom.setChecked(True)
        dialog.custom_folder_edit.setText(str(self.output))
        dialog.appendix_edit.clear()
        with patch("ui.convert_dialog.QMessageBox.information"):
            dialog.start_conversion()
            self.assertIsNotNone(dialog.worker)
            self.assertTrue(dialog.worker.wait(5000))
            self.app.processEvents()
        with Image.open(self.output / "from-dialog.webp") as image:
            self.assert_native_graph(image.getexif(), 0x0110, "prompt", self.prompt)

    def test_stop_button_finishes_only_the_active_file(self):
        sources = [self.make_png(f"image-{number}.png", {"prompt": self.prompt}) for number in range(3)]
        pending_originals = {path: path.read_bytes() for path in sources[1:]}
        dialog = ConvertDialog([str(path) for path in sources])
        self.addCleanup(dialog.close)
        dialog.format_combo.setCurrentText("WebP")
        dialog.keep_comfy_cb.setChecked(True)
        dialog.delete_orig_cb.setChecked(True)
        dialog.radio_custom.setChecked(True)
        dialog.custom_folder_edit.setText(str(self.output))
        dialog.appendix_edit.clear()
        dialog.show()
        self.app.processEvents()

        entered, release = Event(), Event()
        convert_file = ConvertWorker.convert_file

        def pause_first_conversion(worker, source, target):
            if source == str(sources[0]):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the first conversion")
            convert_file(worker, source, target)

        with (patch.object(ConvertWorker, "convert_file", pause_first_conversion),
              patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes),
              patch.object(QMessageBox, "information") as summary):
            QTest.mouseClick(dialog.convert_btn, Qt.MouseButton.LeftButton)
            worker = dialog.worker
            self.assertIsNotNone(worker)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(dialog.close_btn.text(), "Stop after this file")
                QTest.mouseClick(dialog.close_btn, Qt.MouseButton.LeftButton)
            finally:
                release.set()
                self.assertTrue(worker.wait(5000))
            self.app.processEvents()

        summary.assert_called_once()
        _, title, message = summary.call_args.args
        self.assertEqual(title, "Stopped")
        self.assertIn("1 of 3", message)
        self.assertFalse(sources[0].exists())
        self.assertEqual({path: path.read_bytes() for path in sources[1:]}, pending_originals)
        target = self.output / "image-0.webp"
        self.assertEqual(list(self.output.iterdir()), [target])
        self.assertCountEqual(dialog.changed_paths, [str(target), str(sources[0])])
        with Image.open(target) as image:
            self.assert_native_graph(image.getexif(), 0x0110, "prompt", self.prompt)


if __name__ == "__main__":
    unittest.main()
