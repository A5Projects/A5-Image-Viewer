from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from utils.file_ops import get_image_settings
from utils.image_loading import ImageLoadError, read_full_image

class ImageViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        self.smooth_downscaling = get_image_settings()["smooth_downscaling"]
        self.last_error = ""
        self.error_label = QLabel(self.viewport())
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setStyleSheet("background: #252525; color: white; padding: 16px;")
        self.error_label.hide()
        
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
    def load_image(self, file_path):
        self.clear_image()
        try:
            image = read_full_image(file_path)
        except ImageLoadError as error:
            self.last_error = str(error)
            self.error_label.setText(self.last_error)
            self.position_error_label()
            self.error_label.show()
            return False
        self.set_pixmap(QPixmap.fromImage(image))
        return True

    def set_pixmap(self, pixmap):
        if not pixmap.isNull():
            self.last_error = ""
            self.error_label.hide()
            self.pixmap_item.setPixmap(pixmap)
            self.setSceneRect(self.pixmap_item.boundingRect())
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def clear_image(self):
        self.pixmap_item.setPixmap(QPixmap())
        self.setSceneRect(self.pixmap_item.boundingRect())
        self.last_error = ""
        self.error_label.hide()

    def apply_image_settings(self, settings):
        self.smooth_downscaling = settings["smooth_downscaling"]
        self.viewport().update()

    def paintEvent(self, event):
        transform = self.transform()
        scale_x = (transform.m11() ** 2 + transform.m12() ** 2) ** 0.5
        scale_y = (transform.m21() ** 2 + transform.m22() ** 2) ** 0.5
        smooth = self.smooth_downscaling and max(scale_x, scale_y) < 1.0 - 1e-9
        mode = Qt.TransformationMode.SmoothTransformation if smooth else Qt.TransformationMode.FastTransformation
        if self.pixmap_item.transformationMode() != mode:
            self.pixmap_item.setTransformationMode(mode)
        super().paintEvent(event)

    def position_error_label(self):
        width = max(1, min(620, self.viewport().width() - 24))
        self.error_label.setFixedWidth(width)
        self.error_label.adjustSize()
        self.error_label.move(
            max(0, (self.viewport().width() - width) // 2),
            max(0, (self.viewport().height() - self.error_label.height()) // 2),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "error_label"):
            self.position_error_label()

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
