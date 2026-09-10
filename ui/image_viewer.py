from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImageReader

class ImageViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
    def load_image(self, file_path):
        reader = QImageReader(file_path)
        reader.setAutoTransform(False)
        image = reader.read()
        self.set_pixmap(QPixmap.fromImage(image))

    def set_pixmap(self, pixmap):
        if not pixmap.isNull():
            self.pixmap_item.setPixmap(pixmap)
            self.setSceneRect(self.pixmap_item.boundingRect())
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def clear_image(self):
        self.pixmap_item.setPixmap(QPixmap())

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            zoom_in_factor = 1.25
            zoom_out_factor = 1 / zoom_in_factor

            if event.angleDelta().y() > 0:
                zoom_factor = zoom_in_factor
            else:
                zoom_factor = zoom_out_factor

            self.scale(zoom_factor, zoom_factor)
        else:
            super().wheelEvent(event)

    def fit_to_window(self):
        if not self.pixmap_item.pixmap().isNull():
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self):
        self.resetTransform()

    def zoom_in(self):
        self.scale(1.10, 1.10)

    def zoom_out(self):
        self.scale(1 / 1.10, 1 / 1.10)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Print:
            event.ignore()
            return

        step = 50
        if event.key() == Qt.Key.Key_Left:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - step)
        elif event.key() == Qt.Key.Key_Right:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + step)
        elif event.key() == Qt.Key.Key_Up:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - step)
        elif event.key() == Qt.Key.Key_Down:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + step)
        else:
            super().keyPressEvent(event)
