import os
from collections import deque, OrderedDict
from threading import Condition
from PyQt6.QtWidgets import QListView, QStyledItemDelegate, QStyle
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal, QMimeData, QUrl
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QIcon, QPixmap, QImageReader, QImage, QPainter, QColor, QDrag, QPen, QFont, QBrush
from ui.theme import theme_colors

PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole + 1
EXT_ROLE = Qt.ItemDataRole.UserRole + 2
SIZE_ROLE = Qt.ItemDataRole.UserRole + 3
MODIFIED_ROLE = Qt.ItemDataRole.UserRole + 4
WIDTH_ROLE = Qt.ItemDataRole.UserRole + 5
HEIGHT_ROLE = Qt.ItemDataRole.UserRole + 6


def format_thumbnail_file_size(file_size):
    size = float(file_size or 0)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024.0
        unit += 1
    if unit == 0:
        return f"{int(size)} {units[unit]}"
    value = f"{size:.1f}".rstrip("0").rstrip(".")
    return f"{value} {units[unit]}"


def thumbnail_item_label(file_name, ext, kind, file_size=0, width=0, height=0):
    if kind == "folder":
        return file_name
    if kind == "video":
        return f"{format_thumbnail_file_size(file_size)}        {ext.upper()}\n{file_name}"
    if width and height:
        return f"{width}x{height}        {ext.upper()}\n{file_name}"
    return f"        {ext.upper()}\n{file_name}"


def _read_thumbnail_image(file_path, target_size):
    reader = QImageReader(file_path)
    reader.setAutoTransform(False)
    size = reader.size()
    if not size.isValid():
        return size, QImage()
    reader.setScaledSize(size.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
    ))
    return size, reader.read()


def _read_folder_preview_image(file_path, cell_width, cell_height):
    reader = QImageReader(file_path)
    reader.setAutoTransform(False)
    source_size = reader.size()
    if not source_size.isValid():
        return QImage()
    reader.setScaledSize(source_size.scaled(
        cell_width,
        cell_height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
    ))
    return reader.read()

class ThumbnailItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active = bool(option.state & QStyle.StateFlag.State_Active)
        if selected:
            colors = theme_colors()
            painter.save()
            rect = option.rect.adjusted(4, 4, -4, -2)
            fill = QColor(47, 120, 208, 42) if active else QColor(47, 111, 181, 52)
            border = QColor(colors["thumb_border" if active else "thumb_border_inactive"])
            painter.setBrush(QBrush(fill))
            painter.setPen(QPen(border, 2))
            painter.drawRect(rect)
            painter.restore()

        opt = option
        opt.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, opt, index)

class ThumbnailTaskQueue:
    def __init__(self, files, initial_rows, max_awaiting):
        self.files = files
        self.condition = Condition()
        self.running = True
        self.background_paused = False
        self.pending_rows = set(initial_rows)
        self.background_rows = deque(initial_rows)
        self.priority_rows = deque()
        self.priority_set = set()
        self.in_flight = set()
        self.promoted_in_flight = set()
        self.awaiting_delivery = set()
        self.requested_after_delivery = set()
        self.failed_rows = set()
        self.max_awaiting = max(2, int(max_awaiting))

    def take_next(self):
        with self.condition:
            while self.running:
                if len(self.awaiting_delivery) + len(self.in_flight) >= self.max_awaiting:
                    self.condition.wait()
                    continue
                while self.priority_rows:
                    row = self.priority_rows.popleft()
                    self.priority_set.discard(row)
                    if row in self.pending_rows:
                        self.pending_rows.discard(row)
                        self.in_flight.add(row)
                        return row, True

                if not self.background_paused:
                    while self.background_rows:
                        row = self.background_rows.popleft()
                        if row in self.pending_rows:
                            self.pending_rows.discard(row)
                            self.in_flight.add(row)
                            return row, False

                self.condition.wait()
        return None, False

    def request_rows(self, rows):
        with self.condition:
            for row in rows:
                if row < 0 or row >= len(self.files) or self.files[row][4] != "image":
                    continue
                if row in self.failed_rows:
                    continue
                if row in self.in_flight:
                    self.promoted_in_flight.add(row)
                    continue
                if row in self.awaiting_delivery:
                    self.requested_after_delivery.add(row)
                    continue
                self.pending_rows.add(row)
                if row not in self.priority_set:
                    self.priority_rows.append(row)
                    self.priority_set.add(row)
            self.condition.notify_all()

    def retry_rows(self, rows):
        with self.condition:
            for row in rows:
                self.failed_rows.discard(row)
            self.condition.notify_all()
        self.request_rows(rows)

    def add_background_rows(self, rows):
        with self.condition:
            for row in rows:
                if (
                    row < 0 or
                    row >= len(self.files) or
                    self.files[row][4] != "image" or
                    row in self.failed_rows or
                    row in self.in_flight or
                    row in self.awaiting_delivery or
                    row in self.pending_rows
                ):
                    continue
                self.pending_rows.add(row)
                self.background_rows.append(row)
            self.condition.notify_all()

    def task_done(self, row, success):
        with self.condition:
            self.in_flight.discard(row)
            self.promoted_in_flight.discard(row)
            if success:
                self.awaiting_delivery.add(row)
            else:
                self.failed_rows.add(row)
            self.condition.notify_all()

    def is_priority_result(self, row, original_priority):
        with self.condition:
            return original_priority or row in self.promoted_in_flight

    def acknowledge(self, row, admitted):
        with self.condition:
            self.awaiting_delivery.discard(row)
            requested = row in self.requested_after_delivery
            self.requested_after_delivery.discard(row)
            if requested and not admitted and row not in self.failed_rows:
                self.pending_rows.add(row)
                if row not in self.priority_set:
                    self.priority_rows.append(row)
                    self.priority_set.add(row)
            self.condition.notify_all()

    def set_background_paused(self, paused):
        with self.condition:
            self.background_paused = paused
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.running = False
            self.condition.notify_all()


class ThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(int, int, str, str, object, int, int, bool)

    def __init__(self, files, task_queue, generation, target_size):
        super().__init__()
        self.files = files
        self.task_queue = task_queue
        self.generation = generation
        self.target_size = target_size

    def run(self):
        while True:
            row, priority = self.task_queue.take_next()
            if row is None:
                return

            file_path, file_name, ext, _, kind, file_size = self.files[row]
            success = False
            try:
                size, img = _read_thumbnail_image(file_path, self.target_size)
                if size.isValid():
                    display_name = thumbnail_item_label(
                        file_name,
                        ext,
                        kind,
                        file_size,
                        size.width(),
                        size.height(),
                    )
                    if not img.isNull():
                        success = True
                        priority = self.task_queue.is_priority_result(row, priority)
                        self.task_queue.task_done(row, True)
                        self.thumbnail_ready.emit(
                            self.generation,
                            row,
                            file_path,
                            display_name,
                            img,
                            size.width(),
                            size.height(),
                            priority
                        )
            except Exception:
                pass
            if not success:
                self.task_queue.task_done(row, False)


class FolderPreviewQueue:
    def __init__(self, paths):
        self.condition = Condition()
        self.running = True
        self.paused = False
        self.pending = set(paths)
        self.background_paths = deque(paths)
        self.priority_paths = deque()
        self.priority_set = set()

    def take_next(self):
        with self.condition:
            while self.running:
                if self.paused:
                    self.condition.wait()
                    continue
                while self.priority_paths:
                    path = self.priority_paths.popleft()
                    self.priority_set.discard(path)
                    if path in self.pending:
                        self.pending.discard(path)
                        return path
                while self.background_paths:
                    path = self.background_paths.popleft()
                    if path in self.pending:
                        self.pending.discard(path)
                        return path
                return None
        return None

    def prioritize(self, paths):
        with self.condition:
            for path in paths:
                if path in self.pending and path not in self.priority_set:
                    self.priority_paths.append(path)
                    self.priority_set.add(path)
            self.condition.notify_all()

    def set_paused(self, paused):
        with self.condition:
            self.paused = bool(paused)
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.running = False
            self.condition.notify_all()


class FolderPreviewWorker(QThread):
    preview_ready = pyqtSignal(int, str, object)

    def __init__(self, task_queue, generation, target_size, supported_formats,
                 entry_limit=2000, start_delay_ms=1200):
        super().__init__()
        self.task_queue = task_queue
        self.generation = generation
        self.target_size = target_size
        self.supported_formats = set(supported_formats)
        self.entry_limit = max(100, int(entry_limit))
        self.start_delay_ms = max(0, int(start_delay_ms))

    def run(self):
        remaining_delay = self.start_delay_ms
        while remaining_delay > 0:
            if self.isInterruptionRequested():
                return
            interval = min(50, remaining_delay)
            self.msleep(interval)
            remaining_delay -= interval

        while not self.isInterruptionRequested():
            folder_path = self.task_queue.take_next()
            if folder_path is None:
                return
            preview = self.build_preview(folder_path)
            if preview is not None and not preview.isNull() and not self.isInterruptionRequested():
                self.preview_ready.emit(self.generation, folder_path, preview)

    def build_preview(self, folder_path):
        target = self.target_size
        margin = max(4, int(target * 0.04))
        gap = max(2, int(target * 0.025))
        body_top = max(12, int(target * 0.16))
        body_width = target - (margin * 2)
        body_height = target - body_top - margin
        cell_width = max(8, (body_width - (gap * 3)) // 2)
        cell_height = max(8, (body_height - (gap * 3)) // 2)

        images = []
        inspected = 0
        try:
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if self.isInterruptionRequested():
                        return None
                    inspected += 1
                    if inspected > self.entry_limit:
                        break
                    if not entry.is_file():
                        continue
                    extension = os.path.splitext(entry.name)[1][1:].lower()
                    if extension not in self.supported_formats:
                        continue
                    image = _read_folder_preview_image(
                        entry.path, cell_width, cell_height
                    )
                    if not image.isNull():
                        images.append(image)
                    if len(images) == 4:
                        break
        except OSError:
            return None

        if not images:
            return None

        canvas = QImage(target, target, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        folder_color = QColor(232, 184, 55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(folder_color)
        tab_width = max(24, int(target * 0.34))
        tab_height = max(8, int(target * 0.09))
        painter.drawRoundedRect(margin + gap, body_top - tab_height, tab_width, tab_height + 4, 3, 3)
        painter.drawRoundedRect(margin, body_top, body_width, body_height, 3, 3)

        positions = (
            (margin + gap, body_top + gap),
            (margin + (gap * 2) + cell_width, body_top + gap),
            (margin + gap, body_top + (gap * 2) + cell_height),
            (margin + (gap * 2) + cell_width, body_top + (gap * 2) + cell_height),
        )
        painter.setBrush(QColor(28, 28, 28))
        for cell_x, cell_y in positions:
            painter.drawRect(cell_x, cell_y, cell_width, cell_height)

        for image, (cell_x, cell_y) in zip(images, positions):
            scaled = image.scaled(
                cell_width,
                cell_height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            crop_x = max(0, (scaled.width() - cell_width) // 2)
            crop_y = max(0, (scaled.height() - cell_height) // 2)
            painter.drawImage(cell_x, cell_y, scaled.copy(crop_x, crop_y, cell_width, cell_height))
        painter.end()
        return canvas

class ThumbnailView(QListView):
    files_dropped = pyqtSignal(list)
    video_queue_changed = pyqtSignal(int, object)
    video_priority_requested = pyqtSignal(int, object)
    video_background_paused = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("thumbnailView")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setItemDelegate(ThumbnailItemDelegate(self))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(10)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setIconSize(QSize(200, 200))
        self.setGridSize(QSize(230, 278))
        self.setWordWrap(True)
        
        self.thumbnail_model = QStandardItemModel(self)
        self.setModel(self.thumbnail_model)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.placeholder_icon = self._create_placeholder_icon("image")
        self.video_icon = self._create_placeholder_icon("video")
        self.folder_icon = self._create_placeholder_icon("folder")
        self.files = []
        self.path_items = {}
        self.workers = []
        self._old_workers = []
        self.task_queue = None
        self.folder_preview_queue = None
        self.folder_preview_worker = None
        self._old_folder_preview_workers = []
        self.image_generation = 0
        self.thumbnail_workers = 4
        self.thumbnail_cache_limit = 2048 * 1024 * 1024
        self.thumbnail_cache_bytes = 0
        self.thumbnail_cache = OrderedDict()
        self.pinned_paths = set()
        self.cache_background_paused = False
        self.interactive_background_paused = False
        self._last_background_paused = None
        self.filter_text = ""
        self.show_images = True
        self.show_pdfs = True
        self.show_videos = False
        self.show_folders = True
        self.load_generation = 0
        self.visible_item_count = 0
        
    def set_thumbnail_size(self, size):
        size = max(100, min(256, int(size)))
        changed = self.iconSize().width() != size
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 30, size + 78))
        if changed and self.files:
            self.invalidate_all_thumbnails()

    def apply_resource_settings(self, settings):
        worker_count = max(1, int(settings.get("thumbnail_workers", 4)))
        cache_limit = max(256, int(settings.get("thumbnail_cache_mb", 2048))) * 1024 * 1024
        workers_changed = worker_count != self.thumbnail_workers
        old_cache_limit = self.thumbnail_cache_limit
        self.thumbnail_workers = worker_count
        self.thumbnail_cache_limit = cache_limit
        self._evict_to_limit()
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit
        self._update_background_pause()
        if workers_changed and self.files:
            self._start_thumbnail_workers()
        elif cache_limit > old_cache_limit:
            self._resume_background_fill()

    def set_background_activity_paused(self, paused):
        self.interactive_background_paused = bool(paused)
        self._update_background_pause()

    def shutdown(self):
        if self.task_queue is not None:
            self.task_queue.stop()
        if self.folder_preview_queue is not None:
            self.folder_preview_queue.stop()
        if self.folder_preview_worker is not None:
            self.folder_preview_worker.requestInterruption()
        all_workers = self.workers + self._old_workers
        for worker in all_workers:
            worker.wait()
        folder_workers = list(self._old_folder_preview_workers)
        if self.folder_preview_worker is not None:
            folder_workers.append(self.folder_preview_worker)
        for worker in folder_workers:
            worker.requestInterruption()
            worker.wait()
        self.workers = []
        self._old_workers = []
        self.task_queue = None
        self.folder_preview_queue = None
        self.folder_preview_worker = None
        self._old_folder_preview_workers = []
        
    def load_folder(self, folder_path, sort_key="name", reverse=False,
                    show_images=True, show_videos=False, show_folders=True,
                    show_pdfs=True):
        self.load_generation += 1
        self._stop_thumbnail_workers()

        self.show_images = show_images
        self.show_pdfs = show_pdfs
        self.show_videos = show_videos
        self.show_folders = show_folders
        files = self._scan_files(folder_path, sort_key, reverse)
        self.files = files
        self._clear_thumbnail_cache(reset_icons=False)
        self.path_items.clear()
        self.thumbnail_model.clear()
        self.setUpdatesEnabled(False)
        for file_path, file_name, ext, modified_time, kind, file_size in files:
            icon = self._icon_for_kind(kind)
            label = thumbnail_item_label(file_name, ext, kind, file_size)
            item = QStandardItem(icon, label)
            item.setData(file_path, PATH_ROLE)
            item.setData(kind, KIND_ROLE)
            item.setData(ext, EXT_ROLE)
            item.setData(file_size, SIZE_ROLE)
            item.setData(modified_time, MODIFIED_ROLE)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumbnail_model.appendRow(item)
            self.path_items[file_path] = item
        self.setUpdatesEnabled(True)
        self.apply_filter()

        self._start_thumbnail_workers()
        video_paths = [record[0] for record in files if record[4] == "video"]
        self.video_queue_changed.emit(self.load_generation, video_paths)
        self.prioritize_rows_around(0)
        
    def update_thumbnail(self, generation, row, file_path, filename, img, width, height, priority):
        if generation != self.image_generation:
            return
        item = self.thumbnail_model.item(row)
        if item is None or item.data(PATH_ROLE) != file_path:
            item = self.item_for_path(file_path)
            if item is None:
                if self.task_queue is not None:
                    self.task_queue.acknowledge(row, False)
                return

        target_size = self.iconSize().width()
        base_img = QImage(target_size, target_size, QImage.Format.Format_ARGB32_Premultiplied)
        base_img.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(base_img)
        x = (target_size - img.width()) // 2
        y = (target_size - img.height()) // 2
        painter.drawImage(x, y, img)
        painter.end()

        admitted = self._admit_thumbnail(file_path, "image", base_img, priority)
        if admitted:
            item.setText(filename)
            item.setData(width, WIDTH_ROLE)
            item.setData(height, HEIGHT_ROLE)
        if self.task_queue is not None:
            self.task_queue.acknowledge(row, admitted)

    def update_video_thumbnail(self, generation, file_path, img):
        if generation != self.load_generation or img is None or img.isNull():
            return

        item = self.item_for_path(file_path)
        if item is None or item.data(KIND_ROLE) != "video":
            return

        target_size = self.iconSize().width()
        base_img = QImage(target_size, target_size, QImage.Format.Format_ARGB32_Premultiplied)
        base_img.fill(Qt.GlobalColor.transparent)
        scaled = img.scaled(
            target_size,
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        painter = QPainter(base_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = (target_size - scaled.width()) // 2
        y = (target_size - scaled.height()) // 2
        painter.drawImage(x, y, scaled)

        badge_width = max(42, int(target_size * 0.24))
        badge_height = max(30, int(badge_width * 0.7))
        badge_margin = max(6, int(target_size * 0.04))
        badge_x = target_size - badge_width - badge_margin
        badge_y = target_size - badge_height - badge_margin
        self._draw_filmstrip_marker(
            painter,
            badge_x,
            badge_y,
            badge_width,
            badge_height,
            QColor(18, 18, 18, 205),
        )
        painter.end()

        priority = file_path in self.pinned_paths
        if self._admit_thumbnail(file_path, "video", base_img, priority):
            item.setData(img.width(), WIDTH_ROLE)
            item.setData(img.height(), HEIGHT_ROLE)

    def update_folder_thumbnail(self, generation, folder_path, image):
        if generation != self.load_generation or image is None or image.isNull():
            return
        item = self.item_for_path(folder_path)
        if item is None or item.data(KIND_ROLE) != "folder":
            return
        self._admit_thumbnail(folder_path, "folder", image, priority=False)

    def item_for_path(self, file_path):
        item = self.path_items.get(file_path)
        if item is not None or not file_path:
            return item
        target = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))
        for stored_path, stored_item in self.path_items.items():
            stored = os.path.normcase(
                os.path.normpath(os.path.abspath(stored_path))
            )
            if stored == target:
                return stored_item
        return None

    def visible_image_paths(self, editable_only=False):
        paths = []
        for row in range(self.thumbnail_model.rowCount()):
            item = self.thumbnail_model.item(row)
            if (
                item is not None and
                item.data(KIND_ROLE) == "image" and
                not self.isRowHidden(row)
            ):
                path = item.data(PATH_ROLE)
                if path and (
                    not editable_only or
                    os.path.splitext(path)[1].lower() != ".pdf"
                ):
                    paths.append(path)
        return paths

    def register_item(self, item):
        path = item.data(PATH_ROLE) if item is not None else None
        if path:
            self.path_items[path] = item

    def sync_worker_records(self):
        records = []
        for row in range(self.thumbnail_model.rowCount()):
            item = self.thumbnail_model.item(row)
            if item is None:
                continue
            path = item.data(PATH_ROLE)
            records.append((
                path,
                os.path.basename(path),
                item.data(EXT_ROLE) or "",
                item.data(MODIFIED_ROLE) or 0,
                item.data(KIND_ROLE),
                item.data(SIZE_ROLE) or 0
            ))
        self.files = records
        self._start_thumbnail_workers()

    def unregister_path(self, file_path):
        self.path_items.pop(file_path, None)
        self._evict_path(file_path, reset_icon=False)
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit
        self._update_background_pause()
        self._resume_background_fill()

    def rename_indexed_path(self, old_path, new_path, item):
        self.path_items.pop(old_path, None)
        self.path_items[new_path] = item
        cache_entry = self.thumbnail_cache.pop(old_path, None)
        if cache_entry is not None:
            self.thumbnail_cache[new_path] = cache_entry
        if old_path in self.pinned_paths:
            self.pinned_paths.discard(old_path)
            self.pinned_paths.add(new_path)

    def rename_indexed_paths(self, mapping, items):
        for old_path in mapping:
            self.path_items.pop(old_path, None)
        for old_path, new_path in mapping.items():
            item = items.get(old_path)
            if item is not None:
                self.path_items[new_path] = item

        remapped_cache = OrderedDict()
        for path, entry in self.thumbnail_cache.items():
            remapped_cache[mapping.get(path, path)] = entry
        self.thumbnail_cache = remapped_cache
        self.pinned_paths = {mapping.get(path, path) for path in self.pinned_paths}

    def prioritize_rows_around(self, row, radius=80):
        if row < 0:
            return
        if self.interactive_background_paused:
            radius = 0
        start = max(0, row - radius)
        end = min(self.thumbnail_model.rowCount(), row + radius + 1)
        rows = list(range(start, end))
        self._request_image_rows(rows)
        self._request_video_priority(rows)
        self._request_folder_priority(rows)

    def prioritize_visible_thumbnails(self):
        if self.thumbnail_model.rowCount() == 0:
            return

        grid = self.gridSize()
        if grid.width() <= 0 or grid.height() <= 0:
            return

        columns = max(1, self.viewport().width() // grid.width())
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        first = max(0, (top // grid.height()) * columns)
        last = min(
            self.thumbnail_model.rowCount(),
            ((bottom // grid.height()) + 2) * columns
        )
        rows = list(range(first, last))
        self._set_pinned_rows(rows)
        self._request_image_rows(rows)
        self._request_video_priority(rows)
        self._request_folder_priority(rows)

    def _start_thumbnail_workers(self):
        self._stop_thumbnail_workers()
        self.image_generation += 1
        image_rows = [
            row for row, record in enumerate(self.files)
            if record[4] == "image" and record[0] not in self.thumbnail_cache
        ]
        if not image_rows:
            self.task_queue = None
            self._start_folder_preview_worker()
            return

        self.task_queue = ThumbnailTaskQueue(
            self.files,
            image_rows,
            max_awaiting=max(4, self.thumbnail_workers * 2)
        )
        self._update_background_pause(force=True)
        target_size = self.iconSize().width()
        self.workers = []
        for _ in range(self.thumbnail_workers):
            worker = ThumbnailWorker(
                self.files,
                self.task_queue,
                self.image_generation,
                target_size
            )
            worker.thumbnail_ready.connect(self.update_thumbnail)
            self.workers.append(worker)
            worker.start(QThread.Priority.LowPriority)
        self._start_folder_preview_worker()

    def _stop_thumbnail_workers(self):
        self._stop_folder_preview_worker()
        if self.task_queue is not None:
            self.task_queue.stop()
        if self.workers:
            self._old_workers.extend(self.workers)
        self.workers = []
        self.task_queue = None
        self._old_workers = [worker for worker in self._old_workers if worker.isRunning()]

    def _start_folder_preview_worker(self):
        folder_paths = [
            record[0] for record in self.files
            if record[4] == "folder" and record[0] not in self.thumbnail_cache
        ]
        if not folder_paths or not self.show_folders:
            return
        self.folder_preview_queue = FolderPreviewQueue(folder_paths)
        paused = self.cache_background_paused or self.interactive_background_paused
        self.folder_preview_queue.set_paused(paused)
        self.folder_preview_worker = FolderPreviewWorker(
            self.folder_preview_queue,
            self.load_generation,
            self.iconSize().width(),
            self._supported_image_formats(),
        )
        self.folder_preview_worker.preview_ready.connect(self.update_folder_thumbnail)
        self.folder_preview_worker.start(QThread.Priority.LowestPriority)

    def _stop_folder_preview_worker(self):
        if self.folder_preview_queue is not None:
            self.folder_preview_queue.stop()
        if self.folder_preview_worker is not None:
            self.folder_preview_worker.requestInterruption()
            if self.folder_preview_worker.isRunning():
                self._old_folder_preview_workers.append(self.folder_preview_worker)
        self.folder_preview_queue = None
        self.folder_preview_worker = None
        self._old_folder_preview_workers = [
            worker for worker in self._old_folder_preview_workers
            if worker.isRunning()
        ]

    def _request_folder_priority(self, rows):
        if self.folder_preview_queue is None:
            return
        paths = []
        for row in rows:
            if row < 0 or row >= self.thumbnail_model.rowCount():
                continue
            item = self.thumbnail_model.item(row)
            if item is not None and item.data(KIND_ROLE) == "folder":
                path = item.data(PATH_ROLE)
                if path and path not in self.thumbnail_cache:
                    paths.append(path)
        if paths:
            self.folder_preview_queue.prioritize(paths)

    def _request_image_rows(self, rows, retry=False):
        if self.task_queue is None:
            return
        requested = []
        for row in rows:
            if row < 0 or row >= self.thumbnail_model.rowCount():
                continue
            item = self.thumbnail_model.item(row)
            if item is None or item.data(KIND_ROLE) != "image":
                continue
            path = item.data(PATH_ROLE)
            if path and path not in self.thumbnail_cache:
                requested.append(row)
        if retry:
            self.task_queue.retry_rows(requested)
        else:
            self.task_queue.request_rows(requested)

    def _resume_background_fill(self):
        if self.task_queue is None or self.thumbnail_cache_bytes >= self.thumbnail_cache_limit:
            return
        rows = []
        for row, record in enumerate(self.files):
            if record[4] == "image" and record[0] not in self.thumbnail_cache:
                rows.append(row)
        self.task_queue.add_background_rows(rows)

    def request_thumbnail_refresh(self, file_path):
        item = self.item_for_path(file_path)
        if item is None or item.data(KIND_ROLE) != "image":
            return
        self._evict_path(file_path)
        self._request_image_rows([item.row()], retry=True)

    def invalidate_all_thumbnails(self):
        self._stop_thumbnail_workers()
        for item in self.path_items.values():
            kind = item.data(KIND_ROLE)
            if kind in ("image", "video", "folder"):
                item.setIcon(self._icon_for_kind(kind))
        self._clear_thumbnail_cache(reset_icons=False)
        self._start_thumbnail_workers()
        video_paths = [
            record[0] for record in self.files
            if record[4] == "video"
        ]
        self.video_queue_changed.emit(self.load_generation, video_paths)
        self.prioritize_visible_thumbnails()

    def _admit_thumbnail(self, file_path, kind, image, priority):
        cost = max(1, image.bytesPerLine() * image.height())
        existing = self.thumbnail_cache.pop(file_path, None)
        if existing is not None:
            self.thumbnail_cache_bytes -= existing[0]

        if priority:
            self._evict_for_cost(cost, protected_path=file_path)
        elif self.thumbnail_cache_bytes + cost > self.thumbnail_cache_limit:
            self.cache_background_paused = True
            self._update_background_pause()
            return False

        item = self.item_for_path(file_path)
        if item is None:
            return False
        item.setIcon(QIcon(QPixmap.fromImage(image)))
        self.thumbnail_cache[file_path] = (cost, kind)
        self.thumbnail_cache_bytes += cost
        self.thumbnail_cache.move_to_end(file_path)
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit
        self._update_background_pause()
        return True

    def _evict_for_cost(self, cost, protected_path=None):
        while self.thumbnail_cache and self.thumbnail_cache_bytes + cost > self.thumbnail_cache_limit:
            victim = self._oldest_evictable_path(protected_path)
            if victim is None:
                break
            self._evict_path(victim)

    def _evict_to_limit(self):
        while self.thumbnail_cache and self.thumbnail_cache_bytes > self.thumbnail_cache_limit:
            victim = self._oldest_evictable_path()
            if victim is None:
                break
            self._evict_path(victim)
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit

    def _oldest_evictable_path(self, protected_path=None):
        for path in self.thumbnail_cache:
            if path != protected_path and path not in self.pinned_paths:
                return path
        return None

    def _evict_path(self, file_path, reset_icon=True):
        entry = self.thumbnail_cache.pop(file_path, None)
        if entry is None:
            return
        self.thumbnail_cache_bytes = max(0, self.thumbnail_cache_bytes - entry[0])
        if reset_icon:
            item = self.item_for_path(file_path)
            if item is not None:
                item.setIcon(self._icon_for_kind(item.data(KIND_ROLE)))

    def _clear_thumbnail_cache(self, reset_icons=True):
        if reset_icons:
            for path in list(self.thumbnail_cache):
                self._evict_path(path)
        else:
            self.thumbnail_cache.clear()
            self.thumbnail_cache_bytes = 0
        self.cache_background_paused = False
        self.pinned_paths.clear()
        self._update_background_pause()

    def _set_pinned_rows(self, rows):
        paths = set()
        for row in rows:
            item = self.thumbnail_model.item(row)
            if item is not None:
                path = item.data(PATH_ROLE)
                if path:
                    paths.add(path)
        current = self.currentIndex()
        if current.isValid():
            current_path = current.data(PATH_ROLE)
            if current_path:
                paths.add(current_path)
        self.pinned_paths = paths
        for path in paths:
            if path in self.thumbnail_cache:
                self.thumbnail_cache.move_to_end(path)

    def _update_background_pause(self, force=False):
        paused = self.cache_background_paused or self.interactive_background_paused
        if not force and paused == self._last_background_paused:
            return
        self._last_background_paused = paused
        if self.task_queue is not None:
            self.task_queue.set_background_paused(paused)
        if self.folder_preview_queue is not None:
            self.folder_preview_queue.set_paused(paused)
        self.video_background_paused.emit(paused)

    def request_video_thumbnails(self, paths):
        if not self.show_videos:
            return
        video_paths = [
            path for path in paths
            if os.path.splitext(path)[1][1:].lower() in self._supported_video_formats()
        ]
        if video_paths:
            self.video_priority_requested.emit(self.load_generation, video_paths)

    def _request_video_priority(self, rows):
        if not self.show_videos:
            return
        paths = []
        for row in rows:
            item = self.thumbnail_model.item(row)
            if item is not None and item.data(KIND_ROLE) == "video":
                path = item.data(PATH_ROLE)
                if path and path not in self.thumbnail_cache:
                    paths.append(path)
        if paths:
            self.video_priority_requested.emit(self.load_generation, paths)

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        if previous.isValid():
            previous_path = previous.data(PATH_ROLE)
            if previous_path:
                self.pinned_paths.discard(previous_path)
        if current.isValid():
            current_path = current.data(PATH_ROLE)
            if current_path:
                self.pinned_paths.add(current_path)
                if current_path in self.thumbnail_cache:
                    self.thumbnail_cache.move_to_end(current_path)
            self.prioritize_rows_around(current.row())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Print:
            event.ignore()
            return
        super().keyPressEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.prioritize_visible_thumbnails()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.prioritize_visible_thumbnails()

    def startDrag(self, supported_actions):
        indexes = self.selectionModel().selectedIndexes()
        paths = []
        for index in indexes:
            if not index.isValid():
                continue
            kind = index.data(KIND_ROLE)
            if kind == "folder":
                continue
            path = index.data(PATH_ROLE)
            if path:
                paths.append(path)

        if not paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if self.drop_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.drop_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self.drop_paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dropEvent(event)

    def drop_paths(self, event):
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile()
            if path:
                paths.append(path)
        return paths

    def set_filter_text(self, text):
        self.filter_text = text.strip().lower()
        self.apply_filter()

    def set_kind_visibility(self, show_images=True, show_videos=False,
                            show_folders=True, show_pdfs=True):
        self.show_images = show_images
        self.show_pdfs = show_pdfs
        self.show_videos = show_videos
        self.show_folders = show_folders
        self.apply_filter()

    def apply_filter(self):
        visible_count = 0
        for row in range(self.thumbnail_model.rowCount()):
            item = self.thumbnail_model.item(row)
            if item is None:
                continue
            kind = item.data(KIND_ROLE)
            file_path = item.data(PATH_ROLE) or ""
            name = os.path.basename(file_path).lower()
            ext = item.data(EXT_ROLE) or ""
            is_pdf = kind == "image" and ext.lower() == "pdf"
            kind_visible = (
                (kind == "image" and not is_pdf and self.show_images) or
                (is_pdf and self.show_pdfs) or
                (kind == "video" and self.show_videos) or
                (kind == "folder" and self.show_folders)
            )
            text_visible = (
                kind == "folder" or
                not self.filter_text or
                self.filter_text in name or
                self.filter_text in ext
            )
            visible = kind_visible and text_visible
            self.setRowHidden(row, not visible)
            if visible:
                visible_count += 1
        self.visible_item_count = visible_count

    def next_visible_row(self, row, direction):
        count = self.thumbnail_model.rowCount()
        if count == 0:
            return None
        for step in range(1, count + 1):
            candidate = (row + (step * direction)) % count
            if not self.isRowHidden(candidate):
                return candidate
        return None

    def first_visible_row(self):
        for row in range(self.thumbnail_model.rowCount()):
            if not self.isRowHidden(row):
                return row
        return None

    def last_visible_row(self):
        for row in range(self.thumbnail_model.rowCount() - 1, -1, -1):
            if not self.isRowHidden(row):
                return row
        return None

    def _scan_files(self, folder_path, sort_key, reverse):
        supported_formats = self._supported_image_formats()
        video_formats = self._supported_video_formats()
        files = []
        try:
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir():
                        if not self.show_folders:
                            continue
                        ext = ""
                        kind = "folder"
                    elif entry.is_file():
                        _, ext = os.path.splitext(entry.name)
                        ext = ext[1:].lower()
                        if ext == "pdf" and self.show_pdfs:
                            kind = "image"
                        elif (
                            ext != "pdf" and
                            ext in supported_formats and
                            self.show_images
                        ):
                            kind = "image"
                        elif ext in video_formats and self.show_videos:
                            kind = "video"
                        else:
                            continue
                    else:
                        continue

                    try:
                        stat = entry.stat()
                        modified_time = stat.st_mtime
                        file_size = stat.st_size
                    except OSError:
                        modified_time = 0
                        file_size = 0
                    files.append((entry.path, entry.name, ext, modified_time, kind, file_size))
        except Exception:
            return []

        folders = [item for item in files if item[4] == "folder"]
        non_folders = [item for item in files if item[4] != "folder"]

        folders.sort(key=lambda item: item[1].lower())
        if sort_key == "date":
            non_folders.sort(key=lambda item: (item[3], item[1].lower()), reverse=reverse)
        elif sort_key == "type":
            non_folders.sort(key=lambda item: (item[2], item[1].lower()), reverse=reverse)
        else:
            non_folders.sort(key=lambda item: item[1].lower(), reverse=reverse)
        files = folders + non_folders
        return files

    def _supported_image_formats(self):
        formats = {
            "jpg", "jpeg", "png", "bmp", "webp", "gif", "tif", "tiff",
            "pdf",
        }
        for fmt in QImageReader.supportedImageFormats():
            try:
                formats.add(bytes(fmt).decode("ascii").lower())
            except Exception:
                continue
        return formats

    def _supported_video_formats(self):
        return {"mp4", "m4v", "mov", "webm", "mkv", "avi", "wmv"}

    def _icon_for_kind(self, kind):
        if kind == "video":
            return self.video_icon
        if kind == "folder":
            return self.folder_icon
        return self.placeholder_icon

    @staticmethod
    def _draw_filmstrip_marker(painter, x, y, width, height, fill_color):
        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)
        line_width = max(1, int(min(width, height) * 0.055))
        radius = max(3, int(height * 0.12))
        painter.setPen(QPen(QColor(255, 255, 255, 220), line_width))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(x, y, width, height, radius, radius)

        hole_size = max(2, int(height * 0.12))
        hole_y_positions = (
            y + max(line_width + 1, int(height * 0.08)),
            y + height - max(line_width + 1, int(height * 0.08)) - hole_size,
        )
        hole_x_positions = (
            x + int(width * 0.14),
            x + int(width * 0.44),
            x + int(width * 0.74),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        for hole_y in hole_y_positions:
            for hole_x in hole_x_positions:
                painter.drawRoundedRect(hole_x, hole_y, hole_size, hole_size, 1, 1)

        frame_y = y + int(height * 0.28)
        frame_height = max(3, int(height * 0.44))
        frame_x = x + int(width * 0.12)
        frame_width = max(4, int(width * 0.76))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 225), line_width))
        painter.drawRect(frame_x, frame_y, frame_width, frame_height)
        painter.drawLine(
            frame_x + frame_width // 2,
            frame_y,
            frame_x + frame_width // 2,
            frame_y + frame_height,
        )

    def _create_placeholder_icon(self, kind):
        img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(32, 32, 32))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(70, 70, 70), 2))
        painter.drawRect(0, 0, 255, 255)
        if kind == "video":
            self._draw_filmstrip_marker(
                painter,
                48,
                72,
                160,
                112,
                QColor(70, 90, 110),
            )
        elif kind == "folder":
            painter.setBrush(QColor(214, 170, 63))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(45, 90, 166, 105, 10, 10)
            painter.drawRoundedRect(58, 70, 70, 36, 8, 8)
        else:
            painter.setPen(QColor(95, 95, 95))
            font = QFont()
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "IMG")
        painter.end()
        return QIcon(QPixmap.fromImage(img))
