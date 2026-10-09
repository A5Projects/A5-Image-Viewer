import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QTransform
from PyQt6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from ui.crop_board import ResizableRectItem


class SelectionOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_only_one_edge_and_handles_remain_visible_when_deselected_at_all_zoom_levels(self):
        scene = QGraphicsScene()
        view = QGraphicsView(scene)
        rect = QRectF(40, 40, 80, 80)
        selection = ResizableRectItem(rect)
        scene.addItem(selection)
        for scale in (0.5, 1, 2):
            with self.subTest(scale=scale):
                view.setTransform(QTransform.fromScale(scale, scale))
                selection.update_handles_pos()
                rendered = []
                for selected in (True, False):
                    selection.setSelected(selected)
                    image = QImage(int(160 * scale), int(160 * scale), QImage.Format.Format_ARGB32)
                    image.fill(QColor("navy"))
                    painter = QPainter(image)
                    scene.render(painter, QRectF(image.rect()), QRectF(0, 0, 160, 160))
                    painter.end()
                    rendered.append(image)
                    # Away from handles, only the actual top edge is outlined.
                    x = int(60 * scale)
                    outside = QColor("navy")
                    for y in range(int(40 * scale) - 7, int(40 * scale)):
                        self.assertEqual(image.pixelColor(x, y), outside)
                    self.assertEqual(image.pixelColor(x, int(40 * scale)), QColor("cyan"))
                    self.assertEqual(image.pixelColor(int(40 * scale), int(40 * scale)), QColor("white"))
                self.assertEqual(rendered[0], rendered[1])
                self.assertEqual(selection.rect(), rect)
                self.assertEqual(len(selection.handles), 8)
                self.assertEqual(selection.handles[1].width() * scale, 8)
        view.close()


if __name__ == "__main__":
    unittest.main()
