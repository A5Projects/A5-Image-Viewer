import os
from bisect import bisect_left
from collections import deque, OrderedDict
from threading import Condition
from PyQt6.QtWidgets import QListView, QStyledItemDelegate, QStyle
from PyQt6.QtCore import QSize, Qt, QObject, QCoreApplication, QThread, QThreadPool, QRunnable, QTimer, pyqtSignal, pyqtSlot, QMimeData, QUrl, QItemSelection, QItemSelectionModel, QModelIndex
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QIcon, QPixmap, QImageReader, QImage, QPainter, QColor, QDrag, QPen, QFont, QBrush
from ui.theme import theme_colors
from ui.thumbnail_history import PackedThumbnail, ThumbnailHistory
from ui.thumbnail_decode import ThumbnailDecodeBudget, read_scaled_thumbnail
from ui.gif_playback import GifPlayback
from utils.image_loading import ImageLoadError

PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole + 1
EXT_ROLE = Qt.ItemDataRole.UserRole + 2
SIZE_ROLE = Qt.ItemDataRole.UserRole + 3
MODIFIED_ROLE = Qt.ItemDataRole.UserRole + 4
WIDTH_ROLE = Qt.ItemDataRole.UserRole + 5
HEIGHT_ROLE = Qt.ItemDataRole.UserRole + 6
FINGERPRINT_ROLE = Qt.ItemDataRole.UserRole + 7
SORT_ORDER_ROLE = Qt.ItemDataRole.UserRole + 8


def thumbnail_selection(indexes):
    """Build one Qt selection range for each contiguous run of rows."""
    selection = QItemSelection()
    start = previous = None
    for index in sorted(indexes, key=lambda idx: idx.row()):
        if previous is None or index.row() != previous.row() + 1:
            if start is not None:
                selection.select(start, previous)
            start = index
        previous = index
    if start is not None:
        selection.select(start, previous)
    return selection


def thumbnail_fingerprint(stat):
    if os.name == "nt" and hasattr(stat, "st_birthtime_ns"):
        return stat.st_size, stat.st_mtime_ns, stat.st_birthtime_ns
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def history_budget(total_bytes):
    # Leave most of the configured budget for the current grid.
    return min(total_bytes // 4, 256 * 1024 * 1024)


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


def _read_thumbnail_image(file_path, target_size, queue=None):
    return read_scaled_thumbnail(file_path, QSize(target_size, target_size), queue=queue)


def _read_folder_preview_image(file_path, cell_width, cell_height, queue=None):
    _, image = read_scaled_thumbnail(file_path, QSize(cell_width, cell_height), fill=True, queue=queue)
    return image

class ThumbnailItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        view = self.parent()
        if view._gif_icons:
            icon = view._gif_icons.get(index.data(PATH_ROLE))
            if icon is not None:
                option.icon = icon

    def paint(self, painter, option, index):
        view = self.parent()
        if view.gif_playback_enabled and index.data(EXT_ROLE) == "gif":
            view.note_painted_gif(index.data(PATH_ROLE))
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
    def __init__(self, files, initial_rows, max_awaiting, decode_budget):
        self.files = files
        self.decode_budget = decode_budget
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
        self.decode_budget.wake()


class ThumbnailResults(QObject):
    thumbnail = pyqtSignal(int, int, object, object, int, int, bool, object)
    folder = pyqtSignal(int, str, object)


class ThumbnailWorker(QRunnable):
    def __init__(self, files, task_queue, generation, target_size, history, results):
        super().__init__()
        self.files = files
        self.task_queue = task_queue
        self.generation = generation
        self.target_size = target_size
        self.history = history
        self.results = results

    def run(self):
        while True:
            row, priority = self.task_queue.take_next()
            if row is None:
                return

            record = self.files[row]
            file_path, _, _, _, _, _, fingerprint = record
            success = False
            try:
                cached = self.history.get(file_path, fingerprint, self.target_size)
                packed = None
                img = QImage()
                if cached is not None:
                    cost = self.target_size ** 2 * 4
                    budget = self.task_queue.decode_budget
                    if not budget.acquire(cost, self.task_queue):
                        return
                    try:
                        img = cached.image()
                    finally:
                        budget.release(cost)
                if img.isNull():
                    size, img = _read_thumbnail_image(file_path, self.target_size, self.task_queue)
                    width, height = size.width(), size.height()
                    if fingerprint is not None and not img.isNull():
                        packed = PackedThumbnail.pack(img, width, height)
                else:
                    width, height = cached.source_width, cached.source_height
                if not self.task_queue.running:
                    return
                if not img.isNull():
                    priority = self.task_queue.is_priority_result(row, priority)
                    self.task_queue.task_done(row, True)
                    success = True
                    self.results.thumbnail.emit(
                        self.generation, row, record, img, width, height, priority, packed
                    )
            except Exception:
                pass
            if not success:
                self.task_queue.task_done(row, False)
                if self.files[row] is not record:
                    self.task_queue.retry_rows([row])


class FolderPreviewQueue:
    def __init__(self, paths, decode_budget=None):
        self.condition = Condition()
        self.decode_budget = decode_budget
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
        if self.decode_budget is not None:
            self.decode_budget.wake()


class FolderPreviewWorker(QRunnable):
    def __init__(self, task_queue, generation, target_size, supported_formats,
                 entry_limit=2000, start_delay_ms=1200, results=None):
        super().__init__()
        self.task_queue = task_queue
        self.generation = generation
        self.target_size = target_size
        self.supported_formats = set(supported_formats)
        self.entry_limit = max(100, int(entry_limit))
        self.start_delay_ms = max(0, int(start_delay_ms))
        self.results = results

    def run(self):
        with self.task_queue.condition:
            self.task_queue.condition.wait_for(lambda: not self.task_queue.running, self.start_delay_ms / 1000)
        while self.task_queue.running:
            folder_path = self.task_queue.take_next()
            if folder_path is None:
                return
            preview = self.build_preview(folder_path)
            if self.results and preview is not None and not preview.isNull() and self.task_queue.running:
                self.results.folder.emit(self.generation, folder_path, preview)

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
                    if not self.task_queue.running:
                        return None
                    inspected += 1
                    if inspected > self.entry_limit:
                        break
                    if not entry.is_file():
                        continue
                    extension = os.path.splitext(entry.name)[1][1:].lower()
                    if extension not in self.supported_formats:
                        continue
                    try:
                        image = _read_folder_preview_image(entry.path, cell_width, cell_height, self.task_queue)
                    except ImageLoadError:
                        continue
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


class ThumbnailPool(QThreadPool):
    def __init__(self, count, priority):
        # Destroying a view via its Qt parent or Python's cyclic GC can bypass
        # closeEvent. Keep the pool alive until its native reads have returned.
        super().__init__(QCoreApplication.instance())
        self.setMaxThreadCount(count)
        self.setThreadPriority(priority)
        self.queue = None
        self.parent().aboutToQuit.connect(self.stop)
        self.parent().aboutToQuit.connect(self.join)

    @pyqtSlot()
    def stop(self):
        if self.queue is not None:
            self.queue.stop()
            self.queue = None
        self.clear()

    @pyqtSlot()
    def join(self):
        self.waitForDone()

    @pyqtSlot()
    def dispose(self):
        self.stop()
        self.join()
        self.deleteLater()


class ThumbnailView(QListView):
    files_dropped = pyqtSignal(list)
    video_queue_changed = pyqtSignal(int, object)
    video_priority_requested = pyqtSignal(int, object)
    video_background_paused = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gif_playback_enabled = False
        self._painted_gifs = set()
        self._gif_icons = {}
        self._gif_sync_timer = QTimer(self)
        self._gif_sync_timer.setSingleShot(True)
        self._gif_sync_timer.timeout.connect(self._sync_visible_gifs)
        self._gif_playback = GifPlayback(self, max_players=32, byte_limit=128 * 1024 * 1024)
        self._gif_playback.frames_changed.connect(self._update_gif_frames)
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
        self.text_icon = self._create_placeholder_icon("text")
        self.files = []
        self.path_items = {}
        self.image_generation = 0
        self.thumbnail_workers = 4
        total_budget = 2048 * 1024 * 1024
        self.decode_budget = ThumbnailDecodeBudget(self.thumbnail_workers, total_budget)
        self.thumbnail_pool = ThumbnailPool(self.thumbnail_workers, QThread.Priority.LowPriority)
        self.folder_pool = ThumbnailPool(1, QThread.Priority.LowestPriority)
        for pool in (self.thumbnail_pool, self.folder_pool):
            self.destroyed.connect(pool.stop)
            self.destroyed.connect(pool.dispose, Qt.ConnectionType.QueuedConnection)
        # Workers retain this emitter until delivery finishes, even if the
        # receiving view is already being destroyed.
        self.thumbnail_results = ThumbnailResults()
        self.thumbnail_results.thumbnail.connect(self.update_thumbnail, Qt.ConnectionType.QueuedConnection)
        self.thumbnail_results.folder.connect(self.update_folder_thumbnail, Qt.ConnectionType.QueuedConnection)
        self.thumbnail_history = ThumbnailHistory(history_budget(total_budget))
        self.thumbnail_cache_limit = total_budget - self.thumbnail_history.byte_limit
        self.thumbnail_cache_bytes = 0
        self.thumbnail_cache = OrderedDict()
        self.pinned_paths = set()
        self.cache_background_paused = False
        self.interactive_background_paused = False
        self.file_access_paused = False
        self._last_background_paused = None
        self.filter_text = ""
        self.show_images = True
        self.show_pdfs = True
        self.show_videos = False
        self.show_text = False
        self.show_folders = True
        self.load_generation = 0
        self.visible_item_count = 0
        self.visible_rows = []

    @property
    def task_queue(self):
        return self.thumbnail_pool.queue

    @property
    def folder_preview_queue(self):
        return self.folder_pool.queue

    def set_gif_playback(self, enabled):
        enabled = bool(enabled)
        if enabled == self.gif_playback_enabled:
            return
        self.gif_playback_enabled = enabled
        self._reset_gifs()
        self.viewport().update()

    def _reset_gifs(self):
        self._gif_sync_timer.stop()
        self._painted_gifs.clear()
        self._gif_icons.clear()
        self._gif_playback.clear()

    def note_painted_gif(self, path):
        if (path and path not in self._painted_gifs
                and not self.file_access_paused and not self.interactive_background_paused):
            self._painted_gifs.add(path)
            self._gif_sync_timer.start(0)

    def _sync_visible_gifs(self):
        # The delegate discovers GIFs as Qt paints them. Recheck only those few
        # items after a scroll, filter or layout change, independent of folder size.
        visible = []
        viewport = self.viewport().rect()
        for path in self._painted_gifs:
            item = self.item_for_path(path)
            if item is not None and not self.isRowHidden(item.row()):
                rect = self.visualRect(item.index())
                if viewport.intersects(rect):
                    visible.append((rect.top(), rect.left(), path))
        paths = [path for _, _, path in sorted(visible)]
        self._painted_gifs = set(paths)
        self._gif_icons = {path: icon for path, icon in self._gif_icons.items() if path in self._painted_gifs}
        self._gif_playback.set_sources(paths, self.iconSize())

    def _update_gif_frames(self, frames):
        for path, image in frames.items():
            item = self.item_for_path(path)
            if item is None or self.isRowHidden(item.row()):
                continue
            rect = self.visualRect(item.index())
            if not self.viewport().rect().intersects(rect):
                continue
            if image is None:
                self._gif_icons.pop(path, None)
            else:
                canvas = QPixmap(self.iconSize())
                canvas.fill(Qt.GlobalColor.transparent)
                painter = QPainter(canvas)
                painter.drawImage((canvas.width() - image.width()) // 2,
                                  (canvas.height() - image.height()) // 2, image)
                painter.end()
                self._gif_icons[path] = QIcon(canvas)
            self.viewport().update(rect)

    def hideEvent(self, event):
        self._reset_gifs()
        super().hideEvent(event)

    def shutdown_gif_playback(self):
        self.gif_playback_enabled = False
        self._reset_gifs()
        self._gif_playback.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
        
    def set_thumbnail_size(self, size):
        size = max(100, min(256, int(size)))
        changed = self.iconSize().width() != size
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 30, size + 78))
        if changed:
            self.thumbnail_history.clear()
            if self.files:
                self.invalidate_all_thumbnails()

    def apply_resource_settings(self, settings):
        worker_count = max(1, int(settings.get("thumbnail_workers", 4)))
        cache_limit = max(256, int(settings.get("thumbnail_cache_mb", 2048))) * 1024 * 1024
        workers_changed = worker_count != self.thumbnail_workers
        old_cache_limit = self.thumbnail_cache_limit
        self.thumbnail_workers = worker_count
        self.thumbnail_pool.setMaxThreadCount(worker_count)
        self.decode_budget.configure(worker_count, cache_limit)
        self.thumbnail_history.set_limit(history_budget(cache_limit))
        self.thumbnail_cache_limit = cache_limit - self.thumbnail_history.byte_limit
        self._evict_to_limit()
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit
        self._update_background_pause()
        if workers_changed and self.files:
            self._start_thumbnail_workers()
        elif self.thumbnail_cache_limit > old_cache_limit:
            self._resume_background_fill()

    def set_background_activity_paused(self, paused):
        self.interactive_background_paused = bool(paused)
        self._update_background_pause()
        if self.gif_playback_enabled:
            self._reset_gifs()
            self.viewport().update()

    def set_file_access_paused(self, paused):
        """Stop new reads without waiting on an in-progress decoder in the GUI."""
        paused = bool(paused)
        if paused == self.file_access_paused:
            return
        self.file_access_paused = paused
        if self.gif_playback_enabled:
            self._reset_gifs()
            self.viewport().update()
        if paused:
            self._stop_thumbnail_workers()
        else:
            self._start_thumbnail_workers()

    def shutdown(self):
        self.shutdown_gif_playback()
        self._stop_thumbnail_workers()
        self.thumbnail_pool.join()
        self.folder_pool.join()
        self.thumbnail_history.clear()
        
    def load_folder(self, folder_path, sort_key="name", reverse=False,
                    show_images=True, show_videos=False, show_folders=True,
                    show_pdfs=True, show_text=False):
        self.load_generation += 1
        self._reset_gifs()
        self._stop_thumbnail_workers()

        self.show_images = show_images
        self.show_pdfs = show_pdfs
        self.show_text = show_text
        self.show_videos = show_videos
        self.show_folders = show_folders
        files = self._scan_files(folder_path, sort_key, reverse)
        self.files = files
        self._clear_thumbnail_cache(reset_icons=False)
        self.path_items.clear()
        self.thumbnail_model.clear()
        self.setUpdatesEnabled(False)
        target_size = self.iconSize().width()
        for file_path, file_name, ext, modified_time, kind, file_size, fingerprint in files:
            icon = self._icon_for_kind(kind)
            cached = None
            if kind == "image":
                cached = self.thumbnail_history.get(file_path, fingerprint, target_size)
            width = cached.source_width if cached else 0
            height = cached.source_height if cached else 0
            label = thumbnail_item_label(file_name, ext, kind, file_size, width, height)
            item = QStandardItem(icon, label)
            item.setData(file_path, PATH_ROLE)
            item.setData(kind, KIND_ROLE)
            item.setData(ext, EXT_ROLE)
            item.setData(file_size, SIZE_ROLE)
            item.setData(modified_time, MODIFIED_ROLE)
            item.setData(fingerprint, FINGERPRINT_ROLE)
            if cached is not None:
                item.setData(width, WIDTH_ROLE)
                item.setData(height, HEIGHT_ROLE)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumbnail_model.appendRow(item)
            self.register_item(item)
        self.setUpdatesEnabled(True)
        self.apply_filter()

        self._start_thumbnail_workers()
        video_paths = [record[0] for record in files if record[4] == "video"]
        self.video_queue_changed.emit(self.load_generation, video_paths)
        self.prioritize_rows_around(0)
        
    @pyqtSlot(int, int, object, object, int, int, bool, object)
    def update_thumbnail(self, generation, row, record, img, width, height, priority, packed):
        if generation != self.image_generation:
            return
        if self.files[row] is not record:
            # An explicit save/refresh replaced this record while a read was in flight.
            self.task_queue.retry_rows([row])
            self.task_queue.acknowledge(row, False)
            return
        file_path, filename, ext, _, kind, file_size, fingerprint = record
        item = self.thumbnail_model.item(row)
        if item is None or item.data(PATH_ROLE) != file_path:
            item = self.item_for_path(file_path)
            if item is None:
                if self.task_queue is not None:
                    self.task_queue.acknowledge(row, False)
                return

        target_size = self.iconSize().width()
        if packed is not None:
            self.thumbnail_history.put(file_path, fingerprint, target_size, packed)
        base_img = QImage(target_size, target_size, QImage.Format.Format_ARGB32_Premultiplied)
        base_img.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(base_img)
        x = (target_size - img.width()) // 2
        y = (target_size - img.height()) // 2
        painter.drawImage(x, y, img)
        painter.end()

        admitted = self._admit_thumbnail(file_path, "image", base_img, priority)
        if admitted:
            item.setText(thumbnail_item_label(filename, ext, kind, file_size, width, height))
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

    @pyqtSlot(int, str, object)
    def update_folder_thumbnail(self, generation, folder_path, image):
        if generation != self.image_generation or image is None or image.isNull():
            return
        item = self.item_for_path(folder_path)
        if item is None or item.data(KIND_ROLE) != "folder":
            return
        self._admit_thumbnail(folder_path, "folder", image, priority=False)

    def item_for_path(self, file_path):
        if file_path:
            return self.path_items.get(os.path.normcase(os.path.abspath(file_path)))
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
            self.path_items[os.path.normcase(os.path.abspath(path))] = item

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
                item.data(SIZE_ROLE) or 0,
                item.data(FINGERPRINT_ROLE)
            ))
        self.files = records
        self._start_thumbnail_workers()

    def unregister_items(self, items):
        for item in items:
            path = item.data(PATH_ROLE)
            self.path_items.pop(os.path.normcase(os.path.abspath(path)), None)
            if item.data(KIND_ROLE) == "folder":
                self.thumbnail_history.discard_tree(path)
            else:
                self.thumbnail_history.discard(path)
            self._evict_path(path, reset_icon=False)
        self.cache_background_paused = self.thumbnail_cache_bytes >= self.thumbnail_cache_limit
        # sync_worker_records will build the new queue once the model rows are removed.
        self._update_background_pause()

    def rename_indexed_path(self, old_path, new_path, item):
        discard = (self.thumbnail_history.discard_tree if item.data(KIND_ROLE) == "folder"
                   else self.thumbnail_history.discard)
        discard(old_path)
        discard(new_path)
        self.path_items.pop(os.path.normcase(os.path.abspath(old_path)), None)
        self.register_item(item)
        cache_entry = self.thumbnail_cache.pop(old_path, None)
        if cache_entry is not None:
            self.thumbnail_cache[new_path] = cache_entry
        if old_path in self.pinned_paths:
            self.pinned_paths.discard(old_path)
            self.pinned_paths.add(new_path)

    def rename_indexed_paths(self, mapping, items):
        for old_path, new_path in mapping.items():
            self.thumbnail_history.discard(old_path)
            self.thumbnail_history.discard(new_path)
        for old_path in mapping:
            self.path_items.pop(os.path.normcase(os.path.abspath(old_path)), None)
        for old_path, new_path in mapping.items():
            item = items.get(old_path)
            if item is not None:
                self.register_item(item)

        remapped_cache = OrderedDict()
        for path, entry in self.thumbnail_cache.items():
            remapped_cache[mapping.get(path, path)] = entry
        self.thumbnail_cache = remapped_cache
        self.pinned_paths = {mapping.get(path, path) for path in self.pinned_paths}

    def prioritize_rows_around(self, row, radius=80):
        if row < 0 or not self.visible_rows:
            return
        if self.interactive_background_paused:
            radius = 0
        position = bisect_left(self.visible_rows, row)
        rows = self.visible_rows[max(0, position - radius):position + radius + 1]
        self._request_image_rows(rows)
        self._request_video_priority(rows)
        self._request_folder_priority(rows)

    def prioritize_visible_thumbnails(self):
        if self._painted_gifs:
            self._gif_sync_timer.start(0)
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
        rows = self.visible_rows[first:last]
        self._set_pinned_rows(rows)
        self._request_image_rows(rows)
        self._request_video_priority(rows)
        self._request_folder_priority(rows)

    def _uncached_background_rows(self):
        target_size = self.iconSize().width()
        # Warm images are expanded by the workers only when the grid requests them.
        return [
            row for row, record in enumerate(self.files)
            if record[4] == "image" and record[0] not in self.thumbnail_cache
            and self.thumbnail_history.get(record[0], record[6], target_size) is None
        ]

    def _start_thumbnail_workers(self):
        self._stop_thumbnail_workers()
        if self.file_access_paused:
            return
        if not any(record[4] == "image" for record in self.files):
            self._start_folder_preview_worker()
            return

        self.thumbnail_pool.queue = ThumbnailTaskQueue(
            self.files,
            self._uncached_background_rows(),
            max_awaiting=max(4, self.thumbnail_workers * 2),
            decode_budget=self.decode_budget,
        )
        self._update_background_pause(force=True)
        for _ in range(self.thumbnail_workers):
            worker = ThumbnailWorker(
                self.files,
                self.task_queue,
                self.image_generation,
                self.iconSize().width(),
                self.thumbnail_history,
                self.thumbnail_results,
            )
            self.thumbnail_pool.start(worker)
        self._start_folder_preview_worker()
        self.prioritize_visible_thumbnails()

    def _stop_thumbnail_workers(self):
        self.image_generation += 1
        self.folder_pool.stop()
        self.thumbnail_pool.stop()

    def _start_folder_preview_worker(self):
        folder_paths = [
            record[0] for record in self.files
            if record[4] == "folder" and record[0] not in self.thumbnail_cache
        ]
        if not folder_paths or not self.show_folders:
            return
        self.folder_pool.queue = FolderPreviewQueue(folder_paths, self.decode_budget)
        paused = self.cache_background_paused or self.interactive_background_paused
        self.folder_preview_queue.set_paused(paused)
        worker = FolderPreviewWorker(
            self.folder_preview_queue,
            self.image_generation,
            self.iconSize().width(),
            self._supported_image_formats(),
            results=self.thumbnail_results,
        )
        self.folder_pool.start(worker)

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
        self.task_queue.add_background_rows(self._uncached_background_rows())

    def request_thumbnail_refresh(self, file_path):
        self.request_thumbnail_refreshes([file_path])

    def request_thumbnail_refreshes(self, paths):
        rows = []
        for path in paths:
            self.thumbnail_history.discard(path)
            item = self.item_for_path(path)
            if item is None or item.data(KIND_ROLE) != "image":
                continue
            path = item.data(PATH_ROLE)
            self._gif_playback.invalidate(path)
            self._gif_icons.pop(path, None)
            self._evict_path(path)
            row = item.row()
            if 0 <= row < len(self.files) and self.files[row][0] == path:
                # Replacing the tuple also invalidates a pending result for this row,
                # including in-place edits that deliberately preserve the timestamp.
                self.files[row] = (
                    *self.files[row][:5], item.data(SIZE_ROLE) or 0, item.data(FINGERPRINT_ROLE)
                )
            rows.append(row)
        self._request_image_rows(rows, retry=True)

    def invalidate_all_thumbnails(self):
        self.load_generation += 1
        self._reset_gifs()
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

    def jump_to_filename(self, prefix):
        """Cycle through visible names in display order without searching labels."""
        prefix = prefix.casefold()
        if not prefix:
            return False
        count = self.thumbnail_model.rowCount()
        start = self.currentIndex().row()
        for offset in range(1, count + 1):
            row = (start + offset) % count
            if self.isRowHidden(row):
                continue
            index = self.thumbnail_model.index(row, 0)
            path = index.data(PATH_ROLE)
            if path and os.path.basename(path).casefold().startswith(prefix):
                self.selectionModel().setCurrentIndex(
                    index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
                self.scrollTo(index)
                return True
        return False

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.prioritize_visible_thumbnails()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.prioritize_visible_thumbnails()

    def startDrag(self, supported_actions):
        indexes = self.selectedIndexes()
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
        self.filter_text = text
        self.apply_filter()

    def set_kind_visibility(self, show_images=True, show_videos=False,
                            show_folders=True, show_pdfs=True, show_text=False):
        self.show_images = show_images
        self.show_pdfs = show_pdfs
        self.show_text = show_text
        self.show_videos = show_videos
        self.show_folders = show_folders
        self.apply_filter()

    @staticmethod
    def matches_filename_filter(item, terms):
        if item.data(KIND_ROLE) == "folder":
            return True
        name = os.path.basename(item.data(PATH_ROLE) or "").lower()
        ext = (item.data(EXT_ROLE) or "").lower()
        return all(term in name or term in ext for term in terms)

    def apply_filter(self):
        visible_rows = []
        terms = self.filter_text.lower().split()
        for row in range(self.thumbnail_model.rowCount()):
            item = self.thumbnail_model.item(row)
            if item is None:
                continue
            kind = item.data(KIND_ROLE)
            ext = item.data(EXT_ROLE) or ""
            is_pdf = kind == "image" and ext.lower() == "pdf"
            kind_visible = (
                (kind == "image" and not is_pdf and self.show_images) or
                (is_pdf and self.show_pdfs) or
                (kind == "video" and self.show_videos) or
                (kind == "text" and self.show_text) or
                (kind == "folder" and self.show_folders)
            )
            visible = kind_visible and (not terms or self.matches_filename_filter(item, terms))
            self.setRowHidden(row, not visible)
            if visible:
                visible_rows.append(row)
        self.visible_rows = visible_rows
        self.visible_item_count = len(visible_rows)
        self.remove_hidden_selection()
        self.prioritize_visible_thumbnails()

    def remove_hidden_selection(self):
        selection = self.selectionModel()
        selected = selection.selectedIndexes()
        visible = [index for index in selected if not self.isRowHidden(index.row())]
        if len(visible) < len(selected):
            kept = thumbnail_selection(visible)
            selection.select(kept, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        current = self.currentIndex()
        if current.isValid() and self.isRowHidden(current.row()):
            first = min(visible, key=lambda index: index.row(), default=QModelIndex())
            selection.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)

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
                        elif ext == "txt" and self.show_text:
                            kind = "text"
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
                        fingerprint = thumbnail_fingerprint(stat)
                    except OSError:
                        modified_time = 0
                        file_size = 0
                        fingerprint = None
                    files.append((entry.path, entry.name, ext, modified_time, kind, file_size, fingerprint))
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
        if kind == "text":
            return self.text_icon
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
            painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "TXT" if kind == "text" else "IMG")
        painter.end()
        return QIcon(QPixmap.fromImage(img))
