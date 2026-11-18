import os
import unittest

from PyQt6.QtGui import QColor, QImage

from ui.thumbnail_history import PackedThumbnail, ThumbnailHistory


class PackedThumbnailTests(unittest.TestCase):
    def test_opaque_thumbnail_uses_jpeg_and_retains_source_dimensions(self):
        for fmt in (QImage.Format.Format_RGB888, QImage.Format.Format_RGBA8888):
            with self.subTest(fmt=fmt):
                preview = QImage(31, 17, fmt)
                preview.fill(QColor(10, 40, 90))
                packed = PackedThumbnail.pack(preview, 3100, 1700)
                self.assertTrue(packed.data.startswith(b"\xff\xd8"))
                self.assertEqual((packed.source_width, packed.source_height), (3100, 1700))
                self.assertEqual(packed.image().size(), preview.size())

    def test_single_partially_transparent_pixel_survives_losslessly(self):
        preview = QImage(31, 17, QImage.Format.Format_RGBA8888)
        preview.fill(QColor(15, 90, 125))
        preview.setPixelColor(30, 16, QColor(105, 35, 57, 254))
        packed = PackedThumbnail.pack(preview, 3100, 1700)
        self.assertTrue(packed.data.startswith(b"\x89PNG"))
        self.assertEqual(packed.image().convertToFormat(preview.format()), preview)
        self.assertIsNone(PackedThumbnail.pack(QImage(), 0, 0))


class ThumbnailHistoryTests(unittest.TestCase):
    fingerprint = (2201, 12345678900000)
    size = 200

    def setUp(self):
        self.history = ThumbnailHistory(100_000)
        self.thumbnail = PackedThumbnail(300, 700, b"encoded")

    def put(self, name):
        self.history.put(name, self.fingerprint, self.size, self.thumbnail)

    def get(self, name):
        return self.history.get(name, self.fingerprint, self.size)

    def test_budget_evicts_least_recently_used_and_shrinks_immediately(self):
        self.put("a")
        cost = self.history.byte_count
        self.assertGreater(cost, len(self.thumbnail.data))
        self.history.set_limit(2 * cost)
        self.put("b")
        self.assertIs(self.get("a"), self.thumbnail)
        self.put("c")
        self.assertIsNone(self.get("b"))
        self.assertEqual(self.history.byte_count, 2 * cost)
        self.history.set_limit(cost)
        self.assertIsNone(self.get("a"))
        self.assertIs(self.get("c"), self.thumbnail)
        self.assertEqual(self.history.byte_count, cost)

    def test_fingerprint_and_size_misses_keep_a_matching_entry(self):
        self.put("a")
        self.assertIsNone(self.history.get("a", (1, 2), self.size))
        self.assertIsNone(self.history.get("a", self.fingerprint, 128))
        self.assertIs(self.get("a"), self.thumbnail)

    def test_discard_tree_leaves_similarly_named_siblings(self):
        base = os.path.abspath("album")
        child = os.path.join(base, "nested", "image.png")
        sibling = os.path.join(base + "-backup", "image.png")
        self.put(sibling)
        sibling_cost = self.history.byte_count
        self.put(base)
        self.put(child)
        self.history.discard_tree(os.path.join(base, "."))
        self.assertIsNone(self.get(base))
        self.assertIsNone(self.get(child))
        self.assertIs(self.get(sibling), self.thumbnail)
        self.assertEqual(self.history.byte_count, sibling_cost)

    def test_oversized_item_and_clear(self):
        self.put("a")
        self.history.set_limit(self.history.byte_count)
        oversized = PackedThumbnail(1, 1, b"x" * self.history.byte_limit)
        self.history.put("b", self.fingerprint, self.size, oversized)
        self.assertIsNone(self.get("b"))
        self.assertIs(self.get("a"), self.thumbnail)
        self.history.clear()
        self.assertIsNone(self.get("a"))
        self.assertEqual(self.history.byte_count, 0)
