from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QSizePolicy, QStyledItemDelegate, QWidget


class ShortcutDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return self.parent().gridSize()


class ShrinkableButtonStrip(QWidget):
    resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def sizeHint(self):
        return QSize(0, 22)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class FolderShortcutList(QListWidget):
    """Compact text cells, always two columns, with optional pinned rows."""

    def __init__(self, parent=None, pinned=False):
        super().__init__(parent)
        self.pinned = pinned
        self.setProperty("folderShortcuts", True)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSpacing(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if pinned
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.setItemDelegate(ShortcutDelegate(self))
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.update_cell_geometry)
        self.viewport().installEventFilter(self)
        self.update_cell_geometry()

    def update_cell_geometry(self):
        metrics = self.fontMetrics()
        row_height = metrics.height() + 6
        frame = 2 * self.frameWidth()
        self.setMinimumWidth(0)
        if self.pinned:
            self.setFixedHeight(3 * row_height + frame)
        else:
            self.setMinimumHeight(2 * row_height + frame)
        # QListView wraps an exact-fit final cell; leave one pixel of slack.
        size = QSize(max(1, (self.viewport().width() - 1) // 2), row_height)
        if self.gridSize() != size:
            self.setGridSize(size)

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            self._layout_timer.start(0)
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            if hasattr(self, "_layout_timer"):
                self._layout_timer.start(0)
