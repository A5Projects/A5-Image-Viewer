import os
from collections import deque, OrderedDict
from threading import Condition
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, 
                             QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsItem,
                             QCheckBox, QFileDialog, QMessageBox, QMenu, QToolButton)
from PyQt6.QtCore import (Qt, QRectF, QPointF, pyqtSignal, QEvent, QObject,
                          QThread, QSize, QTimer)
from PyQt6.QtGui import (QPixmap, QColor, QPen, QShortcut, QKeySequence, QAction,
                         QImageReader, QIcon, QPainter, QPolygonF, QTransform)
from utils.file_ops import (get_crop_ask_overwrite, set_crop_ask_overwrite,
                            get_crop_auto_name_copies,
                            set_crop_auto_name_copies)


def _read_prefetch_image(path, max_item_bytes):
    stat = os.stat(path)
    fingerprint = (stat.st_size, stat.st_mtime_ns)
    reader = QImageReader(path)
    reader.setAutoTransform(False)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() * 4 > max_item_bytes:
        return None
    image = reader.read()
    if image.isNull():
        return None
    cost = max(1, image.bytesPerLine() * image.height())
    if cost > max_item_bytes:
        return None
    return fingerprint, image, cost


class CropPrefetchQueue:
    def __init__(self):
        self.condition = Condition()
        self.running = True
        self.tasks = deque()

    def set_tasks(self, generation, paths, max_item_bytes):
        with self.condition:
            self.tasks = deque((generation, path, max_item_bytes) for path in paths)
            self.condition.notify_all()

    def take_next(self):
        with self.condition:
            while self.running:
                if self.tasks:
                    return self.tasks.popleft()
                self.condition.wait()
        return None

    def stop(self):
        with self.condition:
            self.running = False
            self.condition.notify_all()


class CropPrefetchWorker(QThread):
    image_ready = pyqtSignal(int, str, object, object, int)

    def __init__(self, task_queue):
        super().__init__()
        self.task_queue = task_queue

    def run(self):
        while True:
            task = self.task_queue.take_next()
            if task is None:
                return
            generation, path, max_item_bytes = task
            try:
                result = _read_prefetch_image(path, max_item_bytes)
                if result is not None:
                    fingerprint, image, cost = result
                    self.image_ready.emit(generation, path, fingerprint, image, cost)
            except Exception:
                continue


class CropPrefetchService(QObject):
    image_ready = pyqtSignal(int, str, object, object, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.generation = 0
        self.worker_count = 0
        self.memory_limit = 0
        self.task_queue = None
        self.workers = []
        self.configure(settings)

    def configure(self, settings):
        worker_count = max(1, min(2, int(settings.get("crop_prefetch_workers", 2))))
        memory_limit = max(128, int(settings.get("crop_prefetch_mb", 512))) * 1024 * 1024
        self.memory_limit = memory_limit
        if worker_count == self.worker_count and self.workers:
            return
        self._stop_workers()
        self.worker_count = worker_count
        self.task_queue = CropPrefetchQueue()
        self.workers = []
        for _ in range(worker_count):
            worker = CropPrefetchWorker(self.task_queue)
            worker.image_ready.connect(self.image_ready.emit)
            self.workers.append(worker)
            worker.start(QThread.Priority.LowPriority)

    def request(self, paths):
        self.generation += 1
        if self.task_queue is not None:
            self.task_queue.set_tasks(self.generation, paths, self.memory_limit)
        return self.generation

    def cancel(self):
        self.generation += 1
        if self.task_queue is not None:
            self.task_queue.set_tasks(self.generation, [], self.memory_limit)

    def shutdown(self):
        self._stop_workers()

    def _stop_workers(self):
        if self.task_queue is not None:
            self.task_queue.stop()
        for worker in self.workers:
            worker.wait()
        self.workers = []
        self.task_queue = None


class ResizableRectItem(QGraphicsRectItem):
    handle_size = 8.0
    handle_space = -4.0

    handle_cursors = {
        1: Qt.CursorShape.SizeFDiagCursor, # Top-Left
        2: Qt.CursorShape.SizeVerCursor,   # Top
        3: Qt.CursorShape.SizeBDiagCursor, # Top-Right
        4: Qt.CursorShape.SizeHorCursor,   # Right
        5: Qt.CursorShape.SizeFDiagCursor, # Bottom-Right
        6: Qt.CursorShape.SizeVerCursor,   # Bottom
        7: Qt.CursorShape.SizeBDiagCursor, # Bottom-Left
        8: Qt.CursorShape.SizeHorCursor    # Left
    }

    def __init__(self, rect, pixmap_item=None, aspect_ratio_cb=None):
        super().__init__(rect)
        self.pixmap_item = pixmap_item
        self.aspect_ratio_cb = aspect_ratio_cb
        self.handles = {}
        self.handle_selected = None
        self.mouse_press_pos = None
        self.mouse_press_rect = None
        
        pen = QPen(QColor(0, 255, 255), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QColor(255, 255, 255, 30)) # slight fill to catch clicks
        
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        
        self.update_handles_pos()

    def handle_at(self, point):
        for k, v in self.handles.items():
            if v.contains(point):
                return k
        return None

    def hoverMoveEvent(self, moveEvent):
        if self.isSelected():
            handle = self.handle_at(moveEvent.pos())
            cursor = Qt.CursorShape.SizeAllCursor if handle is None else self.handle_cursors[handle]
            self.setCursor(cursor)
        super().hoverMoveEvent(moveEvent)

    def hoverLeaveEvent(self, moveEvent):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(moveEvent)

    def mousePressEvent(self, mouseEvent):
        if mouseEvent.button() == Qt.MouseButton.LeftButton:
            self.handle_selected = self.handle_at(mouseEvent.pos())
            if self.handle_selected is None and self.rect().contains(mouseEvent.pos()):
                self.handle_selected = 0 # 0 means move
            
            if self.handle_selected is not None:
                self.mouse_press_pos = mouseEvent.scenePos()
                self.mouse_press_rect = self.rect()
                return # Accept event
        super().mousePressEvent(mouseEvent)

    def mouseMoveEvent(self, mouseEvent):
        if self.handle_selected is not None:
            self.interactive_resize(mouseEvent.scenePos())
        else:
            super().mouseMoveEvent(mouseEvent)

    def mouseReleaseEvent(self, mouseEvent):
        self.handle_selected = None
        self.mouse_press_pos = None
        self.mouse_press_rect = None
        self.update_handles_pos()
        super().mouseReleaseEvent(mouseEvent)

    def boundingRect(self):
        scale = self.get_scale_factor()
        if scale == 0: scale = 1.0
        s = self.handle_size / scale
        o = self.handle_space / scale
        return self.rect().adjusted(-o-s, -o-s, o+s, o+s)

    def interactive_resize(self, mouse_pos):
        rect = self.mouse_press_rect
        diff_local = self.mapFromScene(mouse_pos) - self.mapFromScene(self.mouse_press_pos)

        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        
        if self.handle_selected == 0:
            left += diff_local.x()
            right += diff_local.x()
            top += diff_local.y()
            bottom += diff_local.y()
        else:
            if self.handle_selected in [1, 7, 8]: left += diff_local.x()
            if self.handle_selected in [3, 4, 5]: right += diff_local.x()
            if self.handle_selected in [1, 2, 3]: top += diff_local.y()
            if self.handle_selected in [5, 6, 7]: bottom += diff_local.y()

            # Apply aspect ratio lock if any
            ratio = self.aspect_ratio_cb() if self.aspect_ratio_cb else None
            if ratio is not None:
                w, h = right - left, bottom - top
                if w < 1: w = 1
                if h < 1: h = 1
                
                if self.handle_selected in [2, 6]:
                    w = h * ratio
                    if self.handle_selected == 2: right = left + w # Arbitrary expand right
                    else: right = left + w
                else:
                    h = w / ratio
                    if self.handle_selected in [1, 2, 3]: top = bottom - h
                    else: bottom = top + h

            # Enforce minimum size
            if right - left < 10:
                if self.handle_selected in [1, 7, 8]: left = right - 10
                else: right = left + 10
            if bottom - top < 10:
                if self.handle_selected in [1, 2, 3]: top = bottom - 10
                else: bottom = top + 10

        new_rect = QRectF(left, top, right - left, bottom - top)
        
        # Constrain to pixmap_item bounds
        if self.pixmap_item:
            pix_rect = self.pixmap_item.boundingRect()
            if self.handle_selected == 0:
                width, height = new_rect.width(), new_rect.height()
                if new_rect.left() < pix_rect.left():
                    new_rect.moveLeft(pix_rect.left())
                if new_rect.right() > pix_rect.right():
                    new_rect.moveRight(pix_rect.right())
                if new_rect.top() < pix_rect.top():
                    new_rect.moveTop(pix_rect.top())
                if new_rect.bottom() > pix_rect.bottom():
                    new_rect.moveBottom(pix_rect.bottom())
            else:
                new_rect = new_rect.intersected(pix_rect)

        self.setRect(new_rect)
        self.update_handles_pos()

    def get_scale_factor(self):
        if self.scene() and self.scene().views():
            return self.scene().views()[0].transform().m11()
        return 1.0

    def update_handles_pos(self):
        self.prepareGeometryChange()
        scale = self.get_scale_factor()
        if scale == 0: scale = 1.0
        s = self.handle_size / scale
        o = self.handle_space / scale
        b = self.rect()
        
        self.handles[1] = QRectF(b.left()-o-s, b.top()-o-s, s, s)
        self.handles[2] = QRectF(b.center().x()-s/2, b.top()-o-s, s, s)
        self.handles[3] = QRectF(b.right()+o, b.top()-o-s, s, s)
        self.handles[4] = QRectF(b.right()+o, b.center().y()-s/2, s, s)
        self.handles[5] = QRectF(b.right()+o, b.bottom()+o, s, s)
        self.handles[6] = QRectF(b.center().x()-s/2, b.bottom()+o, s, s)
        self.handles[7] = QRectF(b.left()-o-s, b.bottom()+o, s, s)
        self.handles[8] = QRectF(b.left()-o-s, b.center().y()-s/2, s, s)
        
        # Must call prepareGeometryChange since bounding rect might have changed, but handled by setRect

    def shape(self):
        path = super().shape()
        for v in self.handles.values():
            path.addRect(v)
        return path

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setBrush(QColor("white"))
            pen = QPen(QColor("black"), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for v in self.handles.values():
                painter.drawRect(v)

class CropView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selection_rect_item = None
        self.start_pos = None

    def get_aspect_ratio(self):
        if self.parent() and hasattr(self.parent(), "get_aspect_ratio"):
            return self.parent().get_aspect_ratio()
        return None

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, ResizableRectItem):
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = self.mapToScene(event.pos())
            if self.selection_rect_item is None:
                pixmap_item = None
                for i in self.scene().items():
                    if isinstance(i, QGraphicsPixmapItem):
                        pixmap_item = i
                        break
                self.selection_rect_item = ResizableRectItem(QRectF(), pixmap_item, self.get_aspect_ratio)
                self.scene().addItem(self.selection_rect_item)
            
            self.scene().clearSelection()
            self.selection_rect_item.setSelected(True)
            self.selection_rect_item.setRect(QRectF(self.start_pos, self.start_pos))
            self.selection_rect_item.update_handles_pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start_pos is not None:
            current_pos = self.mapToScene(event.pos())
            
            w = current_pos.x() - self.start_pos.x()
            h = current_pos.y() - self.start_pos.y()
            
            ratio = self.get_aspect_ratio()
            if ratio is not None and w != 0:
                sign_h = 1 if h >= 0 else -1
                h = abs(w) / ratio * sign_h
                current_pos = self.start_pos + QPointF(w, h)
                
            rect = QRectF(self.start_pos, current_pos).normalized()
            
            if self.selection_rect_item and self.selection_rect_item.pixmap_item:
                pix_rect = self.selection_rect_item.pixmap_item.boundingRect()
                rect = rect.intersected(pix_rect)
                if ratio is not None:
                    # Enforce ratio again after intersection
                    rw, rh = rect.width(), rect.height()
                    if rw > 0 and rh > 0:
                        if rw / rh > ratio:
                            rw = rh * ratio
                        else:
                            rh = rw / ratio
                        rect.setWidth(rw)
                        rect.setHeight(rh)
            
            if self.selection_rect_item:
                self.selection_rect_item.setRect(rect)
                self.selection_rect_item.update_handles_pos()
            event.accept()
            return
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_pos is not None:
            self.start_pos = None
            if self.selection_rect_item is not None:
                self.scene().clearSelection()
                self.selection_rect_item.setSelected(True)
                self.selection_rect_item.update_handles_pos()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for item in self.scene().items():
            if isinstance(item, QGraphicsPixmapItem):
                self.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
                if self.selection_rect_item:
                    self.selection_rect_item.update_handles_pos()
                break

class CropBoard(QDialog):
    image_saved = pyqtSignal(str)
    image_changed = pyqtSignal(str)
    _session_navigation_choice = None

    def __init__(self, image_path, parent=None, adjacent_image_cb=None,
                 navigation_paths=None, prefetch_service=None):
        super().__init__(parent)
        self.adjacent_image_cb = adjacent_image_cb
        self.navigation_paths = list(navigation_paths or [])
        self.navigation_positions = {
            path: index for index, path in enumerate(self.navigation_paths)
        }
        self.prefetch_service = prefetch_service
        self.prefetch_generation = 0
        self.prefetch_cache = OrderedDict()
        self.prefetch_cache_bytes = 0
        self.prefetch_connected = False
        self.image_path = image_path
        self.original_pixmap = self.read_pixmap(image_path)
        self.current_pixmap = self.original_pixmap
        self.history = []
        self.saved_any = False
        
        self.setWindowTitle(f"Crop Board - {os.path.basename(image_path)}")
        self.resize(800, 600)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        
        layout = QVBoxLayout(self)
        
        # Tool bar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(3)
        self.tool_buttons = {}
        self.aspect_ratio_combo = QComboBox()
        self.aspect_ratio_combo.addItems(["Free", "1:1", "4:3", "16:9", "21:9"])
        self.aspect_ratio_combo.currentIndexChanged.connect(self.on_aspect_ratio_changed)
        toolbar.addWidget(self.aspect_ratio_combo)

        self.add_symbol_button(
            toolbar, "previous", "Previous image (P / PgUp)",
            lambda: self.open_adjacent_image(-1)
        )
        self.add_symbol_button(
            toolbar, "next", "Next image (N / PgDown)",
            lambda: self.open_adjacent_image(1)
        )
        self.add_symbol_button(toolbar, "crop", "Crop selection (C)", self.perform_crop_in_memory)
        self.add_symbol_button(toolbar, "undo", "Undo (Ctrl+Z)", self.undo)
        self.add_symbol_button(toolbar, "rotate_left", "Rotate 90 degrees left (L)", self.rotate_left)
        self.add_symbol_button(toolbar, "rotate", "Rotate 90 degrees right (R)", self.rotate_right)
        self.add_symbol_button(toolbar, "flip_h", "Flip horizontal (H)", self.flip_horizontal)
        self.add_symbol_button(toolbar, "flip_v", "Flip vertical (V)", self.flip_vertical)
        toolbar.addSpacing(6)
        self.add_symbol_button(toolbar, "reset", "Reset image (Ctrl+R)", self.reset)
        
        toolbar.addStretch()

        self.crop_file_btn = QPushButton("Crop to &File")
        self.crop_file_btn.clicked.connect(self.crop_to_file)
        self.install_button_press_feedback(self.crop_file_btn)
        toolbar.addWidget(self.crop_file_btn)

        self.auto_name_check = QCheckBox("Auto")
        self.auto_name_check.setToolTip(
            "Save Crop to File immediately using the next available _crop name"
        )
        self.auto_name_check.setChecked(get_crop_auto_name_copies())
        self.auto_name_check.toggled.connect(set_crop_auto_name_copies)
        toolbar.addWidget(self.auto_name_check)
        
        self.overwrite_check = QCheckBox("Ask")
        self.overwrite_check.setToolTip("Ask before overwriting the original image")
        self.overwrite_check.setChecked(get_crop_ask_overwrite())
        self.overwrite_check.toggled.connect(set_crop_ask_overwrite)
        toolbar.addWidget(self.overwrite_check)
        
        self.save_btn = QPushButton("&Save")
        self.save_btn.clicked.connect(self.save_file)
        self.install_button_press_feedback(self.save_btn)
        toolbar.addWidget(self.save_btn)

        self.save_next_btn = QPushButton("Crop, Save && Ne&xt")
        self.save_next_btn.clicked.connect(self.crop_save_next)
        self.install_button_press_feedback(self.save_next_btn)
        toolbar.addWidget(self.save_next_btn)
        
        layout.addLayout(toolbar)
        
        # View
        self.view = CropView(self)
        self.view.viewport().installEventFilter(self)
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        layout.addWidget(self.view)
        
        self.pixmap_item = QGraphicsPixmapItem(self.current_pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        
        # Context Menu
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.show_context_menu)
        
        # Shortcuts
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo)
        QShortcut(QKeySequence(Qt.Key.Key_PageDown), self).activated.connect(lambda: self.open_adjacent_image(1))
        QShortcut(QKeySequence(Qt.Key.Key_PageUp), self).activated.connect(lambda: self.open_adjacent_image(-1))
        QShortcut(QKeySequence("C"), self).activated.connect(self.perform_crop_in_memory)
        QShortcut(QKeySequence("F"), self).activated.connect(self.crop_to_file)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.reset)
        QShortcut(QKeySequence("L"), self).activated.connect(self.rotate_left)
        QShortcut(QKeySequence("R"), self).activated.connect(self.rotate_right)
        QShortcut(QKeySequence("H"), self).activated.connect(self.flip_horizontal)
        QShortcut(QKeySequence("V"), self).activated.connect(self.flip_vertical)
        QShortcut(QKeySequence("P"), self).activated.connect(lambda: self.open_adjacent_image(-1))
        QShortcut(QKeySequence("N"), self).activated.connect(lambda: self.open_adjacent_image(1))
        QShortcut(QKeySequence("S"), self).activated.connect(self.save_file)
        QShortcut(QKeySequence("X"), self).activated.connect(self.crop_save_next)
        if self.prefetch_service is not None:
            self.prefetch_service.image_ready.connect(self.on_prefetch_ready)
            self.prefetch_connected = True
            self.schedule_prefetch()

    def add_symbol_button(self, layout, icon_name, tooltip, callback):
        button = QToolButton(self)
        button.setObjectName(f"cropTool_{icon_name}")
        button.setIcon(self.crop_tool_icon(icon_name))
        button.setIconSize(QSize(26, 26))
        button.setFixedSize(34, 34)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        self.install_button_press_feedback(button)
        layout.addWidget(button)
        self.tool_buttons[icon_name] = button
        return button

    def install_button_press_feedback(self, button):
        timer = QTimer(button)
        timer.setSingleShot(True)
        timer.setInterval(140)
        timer.timeout.connect(
            lambda target=button: self.set_button_press_feedback(target, False)
        )
        button._crop_press_timer = timer
        button.pressed.connect(
            lambda target=button: self.set_button_press_feedback(target, True)
        )
        button.released.connect(timer.start)

    @staticmethod
    def set_button_press_feedback(button, active):
        button.setProperty("cropPressFeedback", bool(active))
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def crop_tool_icon(self, icon_name):
        if icon_name in ("crop", "rotate", "rotate_left", "flip_h", "flip_v"):
            owner = self.parent()
            while owner is not None:
                creator = getattr(owner, "create_toolbar_icon", None)
                if creator is not None:
                    return creator(icon_name)
                owner = owner.parent()
        return self.create_local_tool_icon(icon_name)

    def create_local_tool_icon(self, icon_name):
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 42, 42))
        painter.drawRoundedRect(2, 2, 28, 28, 4, 4)

        if icon_name in ("previous", "next"):
            painter.setPen(QPen(QColor(180, 220, 255), 3))
            painter.drawLine(8, 16, 24, 16)
            painter.setBrush(QColor(180, 220, 255))
            painter.setPen(Qt.PenStyle.NoPen)
            if icon_name == "previous":
                points = [QPointF(7, 16), QPointF(14, 9), QPointF(14, 23)]
            else:
                points = [QPointF(25, 16), QPointF(18, 9), QPointF(18, 23)]
            painter.drawPolygon(QPolygonF(points))
        elif icon_name == "undo":
            painter.setPen(QPen(QColor(225, 225, 225), 3))
            painter.drawArc(QRectF(9, 9, 16, 14), 20 * 16, 210 * 16)
            painter.setBrush(QColor(225, 225, 225))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([
                QPointF(7, 12), QPointF(14, 8), QPointF(13, 16)
            ]))
        elif icon_name == "reset":
            color = QColor(255, 218, 70)
            painter.setPen(QPen(color, 3))
            for x1, y1, x2, y2, x3, y3 in [
                (7, 13, 7, 7, 13, 7), (19, 7, 25, 7, 25, 13),
                (7, 19, 7, 25, 13, 25), (19, 25, 25, 25, 25, 19),
            ]:
                painter.drawLine(x1, y1, x2, y2)
                painter.drawLine(x2, y2, x3, y3)
        elif icon_name == "crop":
            painter.setPen(QPen(QColor(120, 220, 255), 3))
            painter.drawLine(10, 5, 10, 22)
            painter.drawLine(10, 22, 27, 22)
            painter.drawLine(5, 10, 22, 10)
            painter.drawLine(22, 10, 22, 27)
        elif icon_name in ("rotate", "rotate_left"):
            if icon_name == "rotate_left":
                painter.save()
                painter.translate(32, 0)
                painter.scale(-1, 1)
            painter.setPen(QPen(QColor(170, 220, 255), 3))
            painter.drawArc(QRectF(8, 7, 17, 17), 40 * 16, 285 * 16)
            painter.setBrush(QColor(170, 220, 255))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([
                QPointF(23, 8), QPointF(28, 9), QPointF(25, 14)
            ]))
            if icon_name == "rotate_left":
                painter.restore()
        elif icon_name in ("flip_h", "flip_v"):
            painter.setPen(QPen(QColor(195, 235, 150), 3))
            if icon_name == "flip_h":
                painter.drawLine(8, 16, 24, 16)
                painter.drawLine(16, 7, 16, 25)
                points = [
                    [QPointF(7, 16), QPointF(12, 11), QPointF(12, 21)],
                    [QPointF(25, 16), QPointF(20, 11), QPointF(20, 21)],
                ]
            else:
                painter.drawLine(16, 8, 16, 24)
                painter.drawLine(7, 16, 25, 16)
                points = [
                    [QPointF(16, 7), QPointF(11, 12), QPointF(21, 12)],
                    [QPointF(16, 25), QPointF(11, 20), QPointF(21, 20)],
                ]
            painter.setBrush(QColor(195, 235, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            for triangle in points:
                painter.drawPolygon(QPolygonF(triangle))
        painter.end()
        return QIcon(pixmap)

    def read_pixmap(self, image_path):
        cached = self._take_prefetched_image(image_path)
        if cached is not None:
            return QPixmap.fromImage(cached)
        reader = QImageReader(image_path)
        reader.setAutoTransform(False)
        return QPixmap.fromImage(reader.read())

    def adjacent_path(self, image_path, direction):
        if self.navigation_paths:
            index = self.navigation_positions.get(image_path)
            if index is None:
                return None
            count = len(self.navigation_paths)
            for step in range(1, count + 1):
                candidate = self.navigation_paths[(index + (step * direction)) % count]
                if os.path.isfile(candidate):
                    return candidate
            return None
        if self.adjacent_image_cb:
            return self.adjacent_image_cb(image_path, direction)
        return None

    def schedule_prefetch(self):
        if self.prefetch_service is None or not self.navigation_paths:
            return
        index = self.navigation_positions.get(self.image_path)
        if index is None:
            return
        count = len(self.navigation_paths)
        paths = []
        for offset in (1, -1, 2, -2):
            candidate = self.navigation_paths[(index + offset) % count]
            if candidate != self.image_path and candidate not in paths and os.path.isfile(candidate):
                paths.append(candidate)
        self.prefetch_generation = self.prefetch_service.request(paths)

    def on_prefetch_ready(self, generation, path, fingerprint, image, cost):
        if generation != self.prefetch_generation or image.isNull():
            return
        if self._fingerprint(path) != fingerprint:
            return

        existing = self.prefetch_cache.pop(path, None)
        if existing is not None:
            self.prefetch_cache_bytes -= existing[2]
        while (
            self.prefetch_cache and
            self.prefetch_cache_bytes + cost > self.prefetch_service.memory_limit
        ):
            _, (_, _, old_cost) = self.prefetch_cache.popitem(last=False)
            self.prefetch_cache_bytes -= old_cost
        if cost <= self.prefetch_service.memory_limit:
            self.prefetch_cache[path] = (fingerprint, image, cost)
            self.prefetch_cache_bytes += cost

    def _take_prefetched_image(self, path):
        entry = self.prefetch_cache.pop(path, None)
        if entry is None:
            return None
        fingerprint, image, cost = entry
        self.prefetch_cache_bytes = max(0, self.prefetch_cache_bytes - cost)
        if fingerprint != self._fingerprint(path):
            return None
        return image

    def _fingerprint(self, path):
        try:
            stat = os.stat(path)
            return (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return None

    def has_unsaved_changes(self):
        return self.current_pixmap.cacheKey() != self.original_pixmap.cacheKey() or bool(self.history)

    def confirm_navigation(self):
        if not self.has_unsaved_changes():
            return True

        if CropBoard._session_navigation_choice == "save":
            saved = self.save_current_file(close_on_success=False)
            if not saved:
                CropBoard._session_navigation_choice = None
            return saved
        if CropBoard._session_navigation_choice == "discard":
            return True

        msg = QMessageBox(self)
        msg.setWindowTitle("Save Changes?")
        msg.setText("Save crop changes before moving to another image?")
        save_btn = msg.addButton("&Save", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("&Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton("&Cancel", QMessageBox.ButtonRole.RejectRole)
        remember_check = QCheckBox("Don't ask again this session", msg)
        msg.setCheckBox(remember_check)
        msg.setDefaultButton(save_btn)

        msg._plain_shortcuts = []
        for sequence, button in (
            ("S", save_btn),
            ("D", discard_btn),
            ("C", cancel_btn),
            (QKeySequence(Qt.Key.Key_Escape), cancel_btn),
        ):
            shortcut = QShortcut(QKeySequence(sequence), msg)
            shortcut.activated.connect(button.click)
            msg._plain_shortcuts.append(shortcut)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == save_btn:
            saved = self.save_current_file(close_on_success=False)
            if saved and remember_check.isChecked():
                CropBoard._session_navigation_choice = "save"
            return saved
        if clicked == discard_btn:
            if remember_check.isChecked():
                CropBoard._session_navigation_choice = "discard"
            return True
        if clicked == cancel_btn:
            return False
        return False

    def confirm_discard_changes(self):
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self,
            "Discard Changes?",
            "Discard unsaved crop changes and move to another image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes

    def load_image(self, image_path):
        self.image_path = image_path
        self.original_pixmap = self.read_pixmap(image_path)
        self.current_pixmap = self.original_pixmap
        self.history.clear()
        self.pixmap_item.setPixmap(self.current_pixmap)

        if self.view.selection_rect_item:
            self.scene.removeItem(self.view.selection_rect_item)
            self.view.selection_rect_item = None

        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.setWindowTitle(f"Crop Board - {os.path.basename(image_path)}")
        self.image_changed.emit(image_path)
        self.schedule_prefetch()

    def open_adjacent_image(self, direction):
        if not self.navigation_paths and not self.adjacent_image_cb:
            return
        if not self.confirm_navigation():
            return
        next_path = self.adjacent_path(self.image_path, direction)
        if next_path:
            self.load_image(next_path)

    def eventFilter(self, obj, event):
        if obj == self.view.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                if event.angleDelta().y() < 0:
                    self.open_adjacent_image(1)
                else:
                    self.open_adjacent_image(-1)
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text().lower()
        modifiers = event.modifiers()
        plain_key = not (
            modifiers & (
                Qt.KeyboardModifier.ControlModifier |
                Qt.KeyboardModifier.AltModifier |
                Qt.KeyboardModifier.MetaModifier
            )
        )

        if key == Qt.Key.Key_PageDown:
            self.open_adjacent_image(1)
            event.accept()
            return
        if key == Qt.Key.Key_PageUp:
            self.open_adjacent_image(-1)
            event.accept()
            return

        if plain_key:
            if text == "c":
                self.perform_crop_in_memory()
                event.accept()
                return
            if text == "f":
                self.crop_to_file()
                event.accept()
                return
            if text == "r":
                self.rotate_right()
                event.accept()
                return
            if text == "l":
                self.rotate_left()
                event.accept()
                return
            if text == "h":
                self.flip_horizontal()
                event.accept()
                return
            if text == "v":
                self.flip_vertical()
                event.accept()
                return
            if text == "p":
                self.open_adjacent_image(-1)
                event.accept()
                return
            if text == "n":
                self.open_adjacent_image(1)
                event.accept()
                return
            if text == "s":
                self.save_file()
                event.accept()
                return
            if text == "x":
                self.crop_save_next()
                event.accept()
                return

        super().keyPressEvent(event)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        crop_action = QAction("Crop Selection", self)
        crop_action.triggered.connect(self.perform_crop_in_memory)
        menu.addAction(crop_action)
        menu.addSeparator()
        rotate_left_action = QAction("Rotate 90 degrees left\tL", self)
        rotate_left_action.triggered.connect(self.rotate_left)
        menu.addAction(rotate_left_action)
        rotate_right_action = QAction("Rotate 90 degrees right\tR", self)
        rotate_right_action.triggered.connect(self.rotate_right)
        menu.addAction(rotate_right_action)
        flip_h_action = QAction("Flip horizontal\tH", self)
        flip_h_action.triggered.connect(self.flip_horizontal)
        menu.addAction(flip_h_action)
        flip_v_action = QAction("Flip vertical\tV", self)
        flip_v_action.triggered.connect(self.flip_vertical)
        menu.addAction(flip_v_action)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def get_aspect_ratio(self):
        text = self.aspect_ratio_combo.currentText()
        if text == "1:1": return 1.0
        if text == "4:3": return 4.0 / 3.0
        if text == "16:9": return 16.0 / 9.0
        if text == "21:9": return 21.0 / 9.0
        return None

    def on_aspect_ratio_changed(self):
        if self.view.selection_rect_item:
            # Re-apply aspect ratio to current rect
            ratio = self.get_aspect_ratio()
            if ratio is not None:
                rect = self.view.selection_rect_item.rect()
                w, h = rect.width(), rect.height()
                if w > 0 and h > 0:
                    if w / h > ratio:
                        w = h * ratio
                    else:
                        h = w / ratio
                    rect.setWidth(w)
                    rect.setHeight(h)
                    self.view.selection_rect_item.setRect(rect)
                    self.view.selection_rect_item.update_handles_pos()

    def perform_crop_in_memory(self):
        if self.view.selection_rect_item and self.view.selection_rect_item.rect().isValid() and not self.view.selection_rect_item.rect().isEmpty():
            rect = self.view.selection_rect_item.rect().toRect()
            cropped = self.current_pixmap.copy(rect)
            self.push_history()
            self.current_pixmap = cropped
            self.update_current_pixmap(clear_selection=True)

    def push_history(self):
        self.history.append(self.current_pixmap)
        if len(self.history) > 5:
            self.history.pop(0)

    def clear_crop_selection(self):
        if self.view.selection_rect_item:
            self.scene.removeItem(self.view.selection_rect_item)
            self.view.selection_rect_item = None

    def update_current_pixmap(self, clear_selection=False):
        self.pixmap_item.setPixmap(self.current_pixmap)
        if clear_selection:
            self.clear_crop_selection()
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def apply_geometric_transform(self, transform):
        if self.current_pixmap.isNull():
            return
        self.push_history()
        self.current_pixmap = self.current_pixmap.transformed(
            transform,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.update_current_pixmap(clear_selection=True)

    def rotate_left(self):
        self.apply_geometric_transform(QTransform().rotate(-90))

    def rotate_right(self):
        self.apply_geometric_transform(QTransform().rotate(90))

    def flip_horizontal(self):
        self.apply_geometric_transform(QTransform().scale(-1, 1))

    def flip_vertical(self):
        self.apply_geometric_transform(QTransform().scale(1, -1))

    def undo(self):
        if self.history:
            self.current_pixmap = self.history.pop()
            self.update_current_pixmap(clear_selection=True)

    def reset(self):
        self.history.clear()
        self.current_pixmap = self.original_pixmap
        self.update_current_pixmap(clear_selection=True)

    def crop_to_file(self):
        if self.view.selection_rect_item and self.view.selection_rect_item.rect().isValid() and not self.view.selection_rect_item.rect().isEmpty():
            rect = self.view.selection_rect_item.rect().toRect()
            cropped = self.current_pixmap.copy(rect)

            default_path = self.unique_cropped_path()
            filters = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All Files (*)"
            if self.auto_name_check.isChecked():
                new_path = default_path
            else:
                new_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Cropped Image",
                    default_path,
                    filters,
                )
            if not new_path:
                return False
            if cropped.save(new_path, quality=-1):
                self.saved_any = True
                self.image_saved.emit(new_path)
                return True
            QMessageBox.warning(
                self,
                "Error",
                "Failed to save the cropped image. Make sure the destination is writable.",
            )
        return False

    def unique_cropped_path(self):
        folder, name = os.path.split(self.image_path)
        stem, extension = os.path.splitext(name)
        candidate = os.path.join(folder, f"{stem}_crop{extension}")
        counter = 2
        while os.path.exists(candidate):
            candidate = os.path.join(
                folder,
                f"{stem}_crop{counter}{extension}",
            )
            counter += 1
        return candidate

    def save_file(self):
        self.save_current_file(close_on_success=False)

    def save_current_file(self, close_on_success=False):
        if self.overwrite_check.isChecked():
            reply = QMessageBox.question(self, "Confirm Overwrite", "Are you sure you want to overwrite the original file?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                return False
                
        if self.current_pixmap.save(self.image_path, quality=-1):
            self.saved_any = True
            self.original_pixmap = self.current_pixmap
            self.history.clear()
            self.image_saved.emit(self.image_path)
            if close_on_success:
                self.accept()
            return True

        QMessageBox.warning(self, "Error", "Failed to save the image. Make sure it is not read-only or unsupported.")
        return False

    def crop_save_next(self):
        self.perform_crop_in_memory()
        if not self.save_current_file(close_on_success=False):
            return

        if not self.navigation_paths and not self.adjacent_image_cb:
            return

        next_path = self.adjacent_path(self.image_path, 1)
        if next_path:
            self.load_image(next_path)

    def done(self, result):
        if self.prefetch_connected and self.prefetch_service is not None:
            try:
                self.prefetch_service.image_ready.disconnect(self.on_prefetch_ready)
            except TypeError:
                pass
            self.prefetch_service.cancel()
            self.prefetch_connected = False
        self.prefetch_cache.clear()
        self.prefetch_cache_bytes = 0
        super().done(result)
