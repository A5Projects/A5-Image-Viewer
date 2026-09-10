import os
import sys
from collections import deque, OrderedDict
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QSplitter, QTreeView, QToolBar, QMenu, QInputDialog, QMessageBox, QApplication, QComboBox,
                             QLineEdit, QToolButton, QSizePolicy, QLabel, QStatusBar, QListWidgetItem, QCheckBox, QFileIconProvider,
                             QWidgetAction, QStyle, QFrame, QHeaderView)
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtCore import Qt, QDir, QSize, QRectF, QPointF, QUrl, QMimeData, QObject, QTimer, pyqtSignal, QEvent, QItemSelectionModel, QFileInfo
from ui.thumbnail_view import (ThumbnailView, PATH_ROLE, KIND_ROLE, EXT_ROLE, SIZE_ROLE,
                               MODIFIED_ROLE, WIDTH_ROLE, HEIGHT_ROLE, thumbnail_item_label)
from ui.image_viewer import ImageViewer
from ui.dialogs import CopyMoveDialog, RenameDialog
from ui.folder_shortcuts import FolderShortcutList, ShrinkableButtonStrip
from ui.theme import apply_theme
from ui.crop_board import CropBoard, CropPrefetchService
from ui.fullscreen_viewer import FullScreenViewer
from ui.settings_dialog import SettingsDialog
from ui.convert_dialog import ConvertDialog
from ui.batch_operations import BatchRenameDialog, BatchRotateDialog
from ui.transfer_conflicts import TransferCoordinator
from PyQt6.QtGui import QShortcut, QKeySequence, QAction, QIcon, QPixmap, QPainter, QColor, QPen, QFont, QPolygonF, QDesktopServices, QImageReader, QImage, QStandardItem
from utils.file_ops import (copy_files as copy_files_batch, move_files as move_files_batch,
                            copy_file_pairs, move_file_pairs,
                            delete_files, add_address_folder, get_address_folders,
                            add_favorite_folder, remove_favorite_folder, get_favorite_folders,
                            get_favorite_display_name, set_favorite_display_name,
                            get_favorite_sort_setting, set_favorite_sort_setting,
                            set_last_folder, get_last_folder, get_startup_behavior, get_thumbnail_size,
                            get_resource_settings, get_ui_theme)
from utils import windows_shell

APP_NAME = "A5ImageViewer"
ICON_FILE = "A5ImageViewer.ico"
EDITABLE_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff",
}

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
except Exception:
    QAudioOutput = None
    QMediaPlayer = None
    QVideoSink = None


class VideoFrameGrabber(QObject):
    frame_ready = pyqtSignal(str, object)
    thumbnail_ready = pyqtSignal(int, str, object)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = None
        self.current_purpose = None
        self.current_generation = 0
        self.generation = 0
        self.enabled = False
        self.background_paused = False
        self.failed_paths = set()
        self.thumbnail_paths = set()
        self.pending_paths = set()
        self.thumbnail_queue = deque()
        self.priority_queue = deque()
        self.priority_paths = set()
        self._accept_frames = False
        self._request_token = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.on_timeout)

        self.player = None
        self.video_sink = None
        self.audio_output = None

    def grab(self, file_path):
        if not self.enabled or self._fingerprint(file_path) in self.failed_paths:
            self.failed.emit(file_path)
            return

        if self.current_path == file_path:
            self.current_purpose = "preview"
            return

        self._cancel_current(requeue_thumbnail=True)
        self._start_request(file_path, "preview", self.generation)

    def set_thumbnail_queue(self, generation, paths):
        self.generation = generation
        self.enabled = bool(paths)
        self.thumbnail_paths = set(paths)
        self.pending_paths = set(paths)
        self.thumbnail_queue = deque(paths)
        self.priority_queue.clear()
        self.priority_paths.clear()
        self._cancel_current()

        if not self.enabled:
            self.shutdown()
            return
        QTimer.singleShot(0, self._process_next)

    def prioritize(self, generation, paths):
        if generation != self.generation or not paths:
            return
        self.enabled = True
        for path in paths:
            if path != self.current_path:
                self.pending_paths.add(path)
                self.thumbnail_paths.add(path)
            if path in self.pending_paths and path not in self.priority_paths:
                self.priority_queue.append(path)
                self.priority_paths.add(path)
        QTimer.singleShot(0, self._process_next)

    def set_background_paused(self, paused):
        self.background_paused = bool(paused)
        if not self.background_paused:
            QTimer.singleShot(0, self._process_next)

    def stop(self):
        self.cancel_preview()

    def cancel_preview(self):
        if self.current_purpose != "preview":
            return
        self._cancel_current(requeue_thumbnail=True)
        QTimer.singleShot(0, self._process_next)

    def shutdown(self):
        self.enabled = False
        self.thumbnail_paths.clear()
        self.pending_paths.clear()
        self.thumbnail_queue.clear()
        self.priority_queue.clear()
        self.priority_paths.clear()
        self._cancel_current()
        if self.player is not None:
            self.player.setSource(QUrl())
            self.player.deleteLater()
            self.player = None
        if self.video_sink is not None:
            self.video_sink.deleteLater()
            self.video_sink = None
        if self.audio_output is not None:
            self.audio_output.deleteLater()
            self.audio_output = None

    def _ensure_backend(self):
        if self.player is not None:
            return True
        if not QMediaPlayer or not QVideoSink:
            return False

        self.player = QMediaPlayer(self)
        self.video_sink = QVideoSink(self)
        self.player.setVideoSink(self.video_sink)
        self.player.errorOccurred.connect(self.on_error)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        if QAudioOutput:
            self.audio_output = QAudioOutput(self)
            self.audio_output.setMuted(True)
            self.audio_output.setVolume(0)
            self.player.setAudioOutput(self.audio_output)
        return True

    def _process_next(self):
        if not self.enabled or self.current_path:
            return

        path = self._take_next_path()
        while path:
            if os.path.isfile(path) and self._fingerprint(path) not in self.failed_paths:
                self._start_request(path, "thumbnail", self.generation)
                return
            path = self._take_next_path()

    def _take_next_path(self):
        while self.priority_queue:
            path = self.priority_queue.popleft()
            self.priority_paths.discard(path)
            if path in self.pending_paths:
                self.pending_paths.discard(path)
                return path

        while self.thumbnail_queue and not self.background_paused:
            path = self.thumbnail_queue.popleft()
            if path in self.pending_paths:
                self.pending_paths.discard(path)
                return path
        return None

    def _start_request(self, file_path, purpose, generation):
        if not self._ensure_backend():
            self.failed_paths.add(self._fingerprint(file_path))
            if purpose == "preview":
                self.failed.emit(file_path)
            QTimer.singleShot(0, self._process_next)
            return

        self.current_path = file_path
        self.current_purpose = purpose
        self.current_generation = generation
        self._accept_frames = False
        self._request_token += 1
        request_token = self._request_token
        try:
            self.video_sink.videoFrameChanged.disconnect()
        except TypeError:
            pass
        self.video_sink.videoFrameChanged.connect(
            lambda frame, token=request_token: self.on_video_frame(frame, token)
        )
        self.timer.start(2500)
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.setPosition(0)
        self.player.play()

    def _cancel_current(self, requeue_thumbnail=False):
        self.timer.stop()
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if requeue_thumbnail and self.current_path in self.thumbnail_paths:
            self.pending_paths.add(self.current_path)
            self.thumbnail_queue.appendleft(self.current_path)
        self.current_path = None
        self.current_purpose = None
        self._accept_frames = False
        self._request_token += 1

    def on_media_status_changed(self, status):
        if self.current_path and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia
        ):
            self._accept_frames = True

    def on_video_frame(self, frame, request_token):
        if (
            request_token != self._request_token or
            not self.current_path or
            not self._accept_frames or
            not frame.isValid()
        ):
            return
        image = frame.toImage()
        if image.isNull():
            return

        path = self.current_path
        purpose = self.current_purpose
        generation = self.current_generation
        self._cancel_current()
        if purpose == "preview":
            self.frame_ready.emit(path, image)
            if generation == self.generation:
                self.pending_paths.discard(path)
                self.thumbnail_ready.emit(generation, path, image)
        elif generation == self.generation:
            self.thumbnail_ready.emit(generation, path, image)
        QTimer.singleShot(0, self._process_next)

    def on_timeout(self):
        path = self.current_path
        if not path:
            return
        purpose = self.current_purpose
        self.failed_paths.add(self._fingerprint(path))
        self._cancel_current()
        if purpose == "preview":
            self.failed.emit(path)
        QTimer.singleShot(0, self._process_next)

    def on_error(self, error, error_string=""):
        path = self.current_path
        if not path:
            return
        purpose = self.current_purpose
        self.failed_paths.add(self._fingerprint(path))
        self._cancel_current()
        if purpose == "preview":
            self.failed.emit(path)
        QTimer.singleShot(0, self._process_next)

    def _fingerprint(self, file_path):
        try:
            stat = os.stat(file_path)
            return (file_path, stat.st_size, stat.st_mtime_ns)
        except OSError:
            return (file_path, 0, 0)

class MainWindow(QMainWindow):
    def __init__(self, startup_path=None):
        super().__init__()
        if QApplication.instance().property("ui_theme") is None:
            apply_theme(get_ui_theme())
        self.startup_path = (
            os.path.abspath(startup_path) if startup_path else None
        )
        self.setWindowTitle(APP_NAME)
        icon_path = self.resource_path(ICON_FILE)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1200, 800)
        
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        main_layout = QVBoxLayout(self.central_widget)
        
        # Toolbar
        self.toolbar = QToolBar()
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(self.toolbar)
        self.add_toolbar_action("copy", "Copy To", "C", self.open_copy_dialog)
        self.add_toolbar_action("move", "Move To", "M", self.open_move_dialog)
        self.add_toolbar_action("crop", "Crop", "X", self.open_crop_board)
        self.add_toolbar_action("adjust", "Adjust Colors & Size", "A", self.open_adjust_board)
        self.add_toolbar_action("convert", "Batch Convert", "B", self.open_convert_dialog)
        self.toolbar.addSeparator()
        self.add_toolbar_action("rotate_left", "Rotate 90 degrees left", "L", self.rotate_image_90_left)
        self.add_toolbar_action("rotate", "Rotate 90 degrees right", "R", self.rotate_image_90)
        self.add_toolbar_action("flip_h", "Flip Horizontal", "H", self.flip_image_horizontal)
        self.add_toolbar_action("flip_v", "Flip Vertical", "V", self.flip_image_vertical)
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar.addWidget(spacer)
        
        self.add_toolbar_action("settings", "Settings", "S", self.open_settings_dialog)

        self.address_toolbar = QToolBar()
        self.address_toolbar.setMovable(False)
        self.address_toolbar.setFloatable(False)
        self.addToolBar(self.address_toolbar)

        address_row = QWidget()
        address_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        address_layout = QHBoxLayout(address_row)
        address_layout.setContentsMargins(0, 0, 0, 0)
        address_layout.setSpacing(6)

        self.address_bar = QComboBox()
        self.address_bar.setEditable(True)
        self.address_bar.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
        self.address_bar.lineEdit().returnPressed.connect(self.on_address_entered)
        self.address_bar.activated.connect(self.on_address_selected)
        address_layout.addWidget(self.address_bar, stretch=1)

        self.sort_combo = QComboBox()
        self.sort_combo.setToolTip("Sort thumbnails")
        self.sort_combo.setFixedWidth(170)
        self.sort_combo.view().setMinimumWidth(170)
        self.sort_combo.addItem("Name A-Z", ("name", False))
        self.sort_combo.addItem("Name Z-A", ("name", True))
        self.sort_combo.addItem("Date Old-New", ("date", False))
        self.sort_combo.addItem("Date New-Old", ("date", True))
        self.sort_combo.addItem("Type A-Z", ("type", False))
        self.sort_combo.addItem("Type Z-A", ("type", True))
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        address_layout.addWidget(self.sort_combo)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(170)
        self.filter_edit.textChanged.connect(self.on_filter_changed)
        address_layout.addWidget(self.filter_edit)

        self.show_menu_button = QToolButton()
        self.show_menu_button.setText("Show")
        self.show_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.show_menu = QMenu(self)
        self._show_options_dirty = False
        show_options_widget = QWidget(self.show_menu)
        show_options_layout = QVBoxLayout(show_options_widget)
        show_options_layout.setContentsMargins(10, 6, 12, 6)
        show_options_layout.setSpacing(4)
        self.show_images_action = QCheckBox("Images")
        self.show_images_action.setChecked(True)
        self.show_pdfs_action = QCheckBox("PDFs")
        self.show_pdfs_action.setChecked(True)
        self.show_videos_action = QCheckBox("Videos")
        self.show_folders_action = QCheckBox("Folders")
        self.show_folders_action.setChecked(True)
        for option in (
            self.show_images_action,
            self.show_pdfs_action,
            self.show_videos_action,
            self.show_folders_action,
        ):
            option.toggled.connect(self.on_show_options_changed)
            show_options_layout.addWidget(option)
        show_options_action = QWidgetAction(self.show_menu)
        show_options_action.setDefaultWidget(show_options_widget)
        self.show_menu.addAction(show_options_action)
        self.show_menu.aboutToHide.connect(self.on_show_menu_hidden)
        self.show_menu_button.setMenu(self.show_menu)
        address_layout.addWidget(self.show_menu_button)

        self.address_toolbar.addWidget(address_row)
        
        # Main Splitter
        self.splitter_h = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter_h)
        
        # Left Panel (Tree + Preview)
        self.splitter_left = QSplitter(Qt.Orientation.Vertical)
        self.splitter_h.addWidget(self.splitter_left)
        
        # Left Top: Quick Access + Tree
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        self.navigation_splitter = QSplitter(Qt.Orientation.Vertical)
        
        quick_lists_row = QWidget()
        quick_lists_row.setObjectName("folderShortcutsPanel")
        quick_lists_layout = QVBoxLayout(quick_lists_row)
        quick_lists_layout.setContentsMargins(0, 0, 0, 0)
        quick_lists_layout.setSpacing(0)

        self.quick_access_list = FolderShortcutList(pinned=True)
        self.quick_access_list.addItems(["Desktop", "Documents", "Downloads", "Pictures", "Videos"])
        for row in range(self.quick_access_list.count()):
            item = self.quick_access_list.item(row)
            item.setToolTip(self.quick_access_path(item.text()))
        self.quick_access_list.itemClicked.connect(self.on_quick_access_clicked)
        self.quick_access_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_access_list.customContextMenuRequested.connect(self.show_quick_access_context_menu)

        self.favorites_list = FolderShortcutList()
        self.favorites_list.itemClicked.connect(self.on_favorite_clicked)
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.customContextMenuRequested.connect(self.show_favorites_context_menu)
        self.load_favorites_list()

        quick_lists_layout.addWidget(self.quick_access_list)
        favorites_divider = QFrame()
        favorites_divider.setObjectName("favoritesDivider")
        favorites_divider.setFixedHeight(1)
        quick_lists_layout.addWidget(favorites_divider)
        quick_lists_layout.addWidget(self.favorites_list, 1)
        
        self.tree_view = QTreeView()
        self.tree_view.setAcceptDrops(True)
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath("")
        self.file_model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)
        self.tree_view.setModel(self.file_model)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tree_view.setHorizontalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.tree_view.header().setStretchLastSection(False)
        self.tree_view.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tree_view.viewport().setAcceptDrops(True)
        self.tree_view.setDragDropMode(QTreeView.DragDropMode.DropOnly)
        for i in range(1, self.file_model.columnCount()):
            self.tree_view.hideColumn(i) # Only show names
        
        self.tree_view.selectionModel().currentChanged.connect(self.on_folder_selected)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_tree_context_menu)

        tree_panel = QWidget()
        tree_panel_layout = QVBoxLayout(tree_panel)
        tree_panel_layout.setContentsMargins(0, 0, 0, 0)
        tree_panel_layout.setSpacing(0)

        self.drive_bar = QWidget()
        self.drive_bar.setObjectName("driveBar")
        self.drive_bar.setFixedHeight(27)
        drive_bar_layout = QHBoxLayout(self.drive_bar)
        drive_bar_layout.setContentsMargins(3, 2, 3, 2)
        drive_bar_layout.setSpacing(2)

        self.drive_buttons_widget = ShrinkableButtonStrip()
        self.drive_buttons_layout = QHBoxLayout(self.drive_buttons_widget)
        self.drive_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.drive_buttons_layout.setSpacing(2)
        self.drive_buttons_widget.resized.connect(self.update_visible_drive_buttons)
        drive_bar_layout.addWidget(self.drive_buttons_widget, 1)

        self.drive_refresh_button = QToolButton()
        self.drive_refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.drive_refresh_button.setToolTip("Refresh available drives")
        self.drive_refresh_button.setFixedSize(23, 22)
        self.drive_refresh_button.clicked.connect(self.refresh_drive_buttons)
        drive_bar_layout.addWidget(self.drive_refresh_button)

        tree_panel_layout.addWidget(self.drive_bar)
        tree_panel_layout.addWidget(self.tree_view, 1)
        
        self.navigation_splitter.addWidget(quick_lists_row)
        self.navigation_splitter.setCollapsible(0, False)
        self.navigation_splitter.addWidget(tree_panel)
        self.navigation_splitter.setSizes([150, 350])
        tree_layout.addWidget(self.navigation_splitter)
        
        self.splitter_left.addWidget(tree_container)
        
        # Left Bottom: Preview
        self.preview_viewer = ImageViewer()
        self.splitter_left.addWidget(self.preview_viewer)
        
        # Right Panel (Thumbnails)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.resource_settings = get_resource_settings()
        self.thumbnail_view = ThumbnailView()
        self.thumbnail_view.set_thumbnail_size(get_thumbnail_size())
        self.thumbnail_view.apply_resource_settings(self.resource_settings)
        self.thumbnail_view.selectionModel().currentChanged.connect(self.on_thumbnail_selected)
        self.thumbnail_view.doubleClicked.connect(self.open_thumbnail_fullscreen)
        self.thumbnail_view.files_dropped.connect(self.copy_dropped_files_to_current_folder)
        self.thumbnail_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnail_view.customContextMenuRequested.connect(self.show_thumbnail_context_menu)
        right_layout.addWidget(self.thumbnail_view, stretch=1)
        
        self.splitter_h.addWidget(right_panel)
        
        self.splitter_h.setSizes([300, 900])
        self.splitter_left.setSizes([500, 300])

        self.current_folder_path = None
        self.sort_key = "name"
        self.sort_reverse = False
        self.show_images = True
        self.show_pdfs = True
        self.show_videos = False
        self.show_folders = True
        self.fullscreen_start_path = None
        self.current_image_path = None
        self.current_item_kind = None
        self.image_modified = False
        self.modified_pixmap = None
        self._session_auto_save_edits = False
        self.navigation_history = []
        self.navigation_index = -1
        self._navigating_history = False
        self.drive_buttons = {}
        self.refresh_drive_buttons()
        self.fullscreen_viewer = FullScreenViewer(self)
        self.transfer_coordinator = TransferCoordinator(
            self.transfer_dialog_parent,
            self.execute_queued_transfer,
            self,
        )
        self.transfer_coordinator.job_finished.connect(
            self.on_queued_transfer_finished
        )
        self.video_frame_grabber = VideoFrameGrabber(self)
        self.video_frame_grabber.frame_ready.connect(self.on_video_frame_ready)
        self.video_frame_grabber.thumbnail_ready.connect(self.on_video_thumbnail_ready)
        self.thumbnail_view.video_queue_changed.connect(self.video_frame_grabber.set_thumbnail_queue)
        self.thumbnail_view.video_priority_requested.connect(self.video_frame_grabber.prioritize)
        self.thumbnail_view.video_background_paused.connect(self.video_frame_grabber.set_background_paused)
        self.crop_prefetch_service = CropPrefetchService(self.resource_settings, self)
        self.viewer_prefetch_generation = 0
        self.viewer_prefetch_cache = OrderedDict()
        self.viewer_prefetch_cache_bytes = 0
        self.crop_prefetch_service.image_ready.connect(self.on_viewer_prefetch_ready)
        QApplication.instance().aboutToQuit.connect(self.thumbnail_view.shutdown)
        QApplication.instance().aboutToQuit.connect(self.crop_prefetch_service.shutdown)
        QApplication.instance().aboutToQuit.connect(self.transfer_coordinator.shutdown)
        self.load_address_history()

        self.status_label = QLabel()
        self.status_label.setContentsMargins(4, 0, 4, 0)
        status_bar = QStatusBar()
        status_bar.setFixedHeight(18)
        status_bar.setSizeGripEnabled(False)
        status_bar.addPermanentWidget(self.status_label, 1)
        self.setStatusBar(status_bar)
        self.update_status_bar()
        
        shortcut_c = QShortcut(QKeySequence("C"), self)
        shortcut_c.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_c.activated.connect(self.open_copy_dialog)
        
        shortcut_m = QShortcut(QKeySequence("M"), self)
        shortcut_m.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_m.activated.connect(self.open_move_dialog)
        
        shortcut_x = QShortcut(QKeySequence("X"), self)
        shortcut_x.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_x.activated.connect(self.open_crop_board)
        
        shortcut_f2 = QShortcut(QKeySequence("F2"), self)
        shortcut_f2.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_f2.activated.connect(self.rename_file)

        shortcut_f3 = QShortcut(QKeySequence("F3"), self)
        shortcut_f3.activated.connect(self.open_in_associated_program)

        if windows_shell.is_windows():
            shortcut_f4 = QShortcut(QKeySequence("F4"), self)
            shortcut_f4.activated.connect(self.open_in_associated_editor)
        
        shortcut_ctrl_c = QShortcut(QKeySequence("Ctrl+C"), self)
        shortcut_ctrl_c.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_ctrl_c.activated.connect(self.copy_to_clipboard)

        shortcut_ctrl_x = QShortcut(QKeySequence("Ctrl+X"), self)
        shortcut_ctrl_x.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_ctrl_x.activated.connect(self.cut_to_clipboard)

        shortcut_ctrl_v = QShortcut(QKeySequence("Ctrl+V"), self)
        shortcut_ctrl_v.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_ctrl_v.activated.connect(self.paste_from_clipboard)

        shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        shortcut_f5.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_f5.activated.connect(self.refresh_folder)

        shortcut_a = QShortcut(QKeySequence("A"), self)
        shortcut_a.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_a.activated.connect(self.open_adjust_board)

        shortcut_r = QShortcut(QKeySequence("R"), self)
        shortcut_r.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_r.activated.connect(self.rotate_image_90)

        shortcut_l = QShortcut(QKeySequence("L"), self)
        shortcut_l.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_l.activated.connect(self.rotate_image_90_left)
        
        shortcut_h = QShortcut(QKeySequence("H"), self)
        shortcut_h.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_h.activated.connect(self.flip_image_horizontal)
        
        shortcut_v = QShortcut(QKeySequence("V"), self)
        shortcut_v.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_v.activated.connect(self.flip_image_vertical)

        shortcut_enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self.thumbnail_view)
        shortcut_enter.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut_enter.activated.connect(self.open_current_thumbnail_fullscreen)

        shortcut_keypad_enter = QShortcut(QKeySequence(Qt.Key.Key_Enter), self.thumbnail_view)
        shortcut_keypad_enter.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut_keypad_enter.activated.connect(self.open_current_thumbnail_fullscreen)

        shortcut_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.thumbnail_view)
        shortcut_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_delete.activated.connect(self.delete_selected_files)

        shortcut_shift_delete = QShortcut(QKeySequence("Shift+Delete"), self.thumbnail_view)
        shortcut_shift_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_shift_delete.activated.connect(lambda: self.delete_selected_files(permanent=True))

        shortcut_backspace_thumbs = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.thumbnail_view)
        shortcut_backspace_thumbs.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_backspace_thumbs.activated.connect(self.go_to_parent_folder)

        shortcut_backspace_tree = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.tree_view)
        shortcut_backspace_tree.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_backspace_tree.activated.connect(self.go_to_parent_folder)

        shortcut_alt_left = QShortcut(QKeySequence("Alt+Left"), self)
        shortcut_alt_left.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_alt_left.activated.connect(self.go_back_folder)

        shortcut_alt_right = QShortcut(QKeySequence("Alt+Right"), self)
        shortcut_alt_right.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_alt_right.activated.connect(self.go_forward_folder)

        self.thumbnail_view.installEventFilter(self)
        self.thumbnail_view.viewport().installEventFilter(self)
        self.tree_view.viewport().installEventFilter(self)
        if self.startup_path:
            QTimer.singleShot(
                0, lambda path=self.startup_path: self.open_startup_path(path)
            )
        else:
            QTimer.singleShot(0, self.restore_last_folder)

    def resource_path(self, filename):
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename),
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), filename),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    @staticmethod
    def folder_window_title(folder_path):
        if not folder_path:
            return APP_NAME
        normalized = os.path.normpath(os.path.abspath(folder_path))
        folder_name = os.path.basename(normalized.rstrip("\\/"))
        if folder_name:
            return folder_name
        drive, _ = os.path.splitdrive(normalized)
        return drive or QDir.toNativeSeparators(normalized)

    def update_folder_window_title(self, folder_path=None):
        if folder_path is None:
            folder_path = self.current_folder_path
        self.setWindowTitle(self.folder_window_title(folder_path))

    def add_toolbar_action(self, icon_name, tooltip, shortcut, callback):
        action = QAction(self.create_toolbar_icon(icon_name), "", self)
        action.setToolTip(f"{tooltip} ({shortcut})")
        action.setStatusTip(f"{tooltip} ({shortcut})")
        action.triggered.connect(callback)
        self.toolbar.addAction(action)

    def create_toolbar_icon(self, icon_name):
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 42, 42))
        painter.drawRoundedRect(2, 2, 28, 28, 4, 4)

        if icon_name in ("copy", "move"):
            color = QColor(255, 220, 70) if icon_name == "copy" else QColor(255, 174, 70)
            painter.setPen(color)
            font = QFont()
            font.setBold(True)
            font.setPointSize(17)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "C" if icon_name == "copy" else "M")
        elif icon_name == "crop":
            pen = QPen(QColor(120, 220, 255), 3)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
            painter.setPen(pen)
            painter.drawLine(10, 5, 10, 22)
            painter.drawLine(10, 22, 27, 22)
            painter.drawLine(5, 10, 22, 10)
            painter.drawLine(22, 10, 22, 27)
        elif icon_name == "adjust":
            painter.setPen(QPen(QColor(255, 218, 70), 2))
            painter.drawRect(7, 7, 18, 18)
            painter.drawEllipse(QPointF(16, 16), 4, 4)
            for x1, y1, x2, y2 in [
                (16, 10, 16, 7), (16, 22, 16, 25), (10, 16, 7, 16), (22, 16, 25, 16),
                (12, 12, 10, 10), (20, 12, 22, 10), (12, 20, 10, 22), (20, 20, 22, 22)
            ]:
                painter.drawLine(x1, y1, x2, y2)
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
        elif icon_name == "flip_h":
            painter.setPen(QPen(QColor(195, 235, 150), 3))
            painter.drawLine(8, 16, 24, 16)
            painter.drawLine(16, 7, 16, 25)
            painter.setBrush(QColor(195, 235, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(7, 16), QPointF(12, 11), QPointF(12, 21)]))
            painter.drawPolygon(QPolygonF([QPointF(25, 16), QPointF(20, 11), QPointF(20, 21)]))
        elif icon_name == "flip_v":
            painter.setPen(QPen(QColor(195, 235, 150), 3))
            painter.drawLine(16, 8, 16, 24)
            painter.drawLine(7, 16, 25, 16)
            painter.setBrush(QColor(195, 235, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(16, 7), QPointF(11, 12), QPointF(21, 12)]))
            painter.drawPolygon(QPolygonF([QPointF(16, 25), QPointF(11, 20), QPointF(21, 20)]))
        elif icon_name == "settings":
            painter.setPen(QPen(QColor(200, 200, 200), 2))
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawEllipse(11, 11, 10, 10)
            painter.setPen(QPen(QColor(200, 200, 200), 3))
            painter.drawLine(16, 5, 16, 8)
            painter.drawLine(16, 24, 16, 27)
            painter.drawLine(5, 16, 8, 16)
            painter.drawLine(24, 16, 27, 16)
            painter.drawLine(8, 8, 10, 10)
            painter.drawLine(22, 22, 24, 24)
            painter.drawLine(8, 24, 10, 22)
            painter.drawLine(22, 8, 24, 10)
        elif icon_name == "convert":
            painter.setPen(QPen(QColor(100, 255, 150), 2))
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawRect(6, 6, 12, 12)
            painter.drawRect(14, 14, 12, 12)
            painter.setPen(QPen(QColor(100, 255, 150), 3))
            painter.drawLine(18, 12, 22, 16)
            painter.drawLine(18, 16, 22, 12)

        painter.end()
        return QIcon(pixmap)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and event.key() == Qt.Key.Key_Print:
            event.ignore()
            return False

        if obj == self.tree_view.viewport():
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                paths = self.drop_paths_from_event(event)
                folder_path = self.tree_drop_folder(event)
                if paths and folder_path:
                    event.setDropAction(self.drop_action_for_paths(paths, folder_path, self.event_keyboard_modifiers(event)))
                    event.accept()
                    return True
            if event.type() == QEvent.Type.Drop:
                paths = self.drop_paths_from_event(event)
                folder_path = self.tree_drop_folder(event)
                if paths and folder_path:
                    action = self.drop_action_for_paths(paths, folder_path, self.event_keyboard_modifiers(event))
                    self.transfer_files_to_folder(paths, folder_path, move_files=action == Qt.DropAction.MoveAction)
                    event.setDropAction(action)
                    event.accept()
                    return True

        if obj == self.thumbnail_view.viewport():
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                paths = self.drop_paths_from_event(event)
                folder_path = self.thumbnail_drop_folder(event)
                if paths and folder_path:
                    event.setDropAction(
                        self.drop_action_for_paths(
                            paths,
                            folder_path,
                            self.event_keyboard_modifiers(event),
                        )
                    )
                    event.accept()
                    return True
            if event.type() == QEvent.Type.Drop:
                paths = self.drop_paths_from_event(event)
                folder_path = self.thumbnail_drop_folder(event)
                if paths and folder_path:
                    action = self.drop_action_for_paths(
                        paths,
                        folder_path,
                        self.event_keyboard_modifiers(event),
                    )
                    self.transfer_files_to_folder(
                        paths,
                        folder_path,
                        move_files=action == Qt.DropAction.MoveAction,
                    )
                    event.setDropAction(action)
                    event.accept()
                    return True
        if obj in (self.thumbnail_view, self.thumbnail_view.viewport()):
            search_text = self.thumbnail_shift_search_text(event)
            if search_text and event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if search_text and event.type() == QEvent.Type.KeyPress:
                self.thumbnail_view.keyboardSearch(search_text)
                event.accept()
                return True

        if event.type() == QEvent.Type.MouseButtonPress:
            button = event.button()
            back_buttons = [
                getattr(Qt.MouseButton, "BackButton", None),
                getattr(Qt.MouseButton, "ExtraButton1", None),
            ]
            if button in [b for b in back_buttons if b is not None]:
                self.go_back_folder()
                event.accept()
                return True
            forward_buttons = [
                getattr(Qt.MouseButton, "ForwardButton", None),
                getattr(Qt.MouseButton, "ExtraButton2", None),
            ]
            if button in [b for b in forward_buttons if b is not None]:
                self.go_forward_folder()
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Print:
            event.ignore()
            return
        super().keyPressEvent(event)

    def thumbnail_shift_search_text(self, event):
        if event.type() not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return ""

        modifiers = event.modifiers()
        if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            return ""
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return ""

        text = event.text()
        if len(text) == 1 and text.isalpha():
            return text.lower()
        return ""

    def load_address_history(self):
        self.address_bar.blockSignals(True)
        for folder_path in get_address_folders():
            if os.path.isdir(folder_path) and self.address_bar.findText(folder_path) < 0:
                self.address_bar.addItem(folder_path)
        self.address_bar.blockSignals(False)

    def restore_last_folder(self):
        if get_startup_behavior() != "last_used":
            return
        folder_path = get_last_folder()
        if folder_path and os.path.isdir(folder_path):
            self.navigate_to_folder(folder_path)

    def open_startup_path(self, startup_path):
        path = os.path.abspath(startup_path)
        if os.path.isdir(path):
            self.navigate_to_folder(path)
            return True
        if not os.path.isfile(path):
            return False

        folder_path = os.path.dirname(path)
        self.navigate_to_folder(folder_path)
        item = self.thumbnail_view.item_for_path(path)
        if item is None:
            return False

        index = self.thumbnail_view.model().indexFromItem(item)
        if not index.isValid():
            return False
        model_path = index.data(PATH_ROLE)
        self.select_image_by_path(model_path)
        if index.data(KIND_ROLE) == "image":
            self.open_thumbnail_fullscreen(index)
        return True

    def remember_folder(self, folder_path, add_to_navigation_history=True):
        if not folder_path:
            return

        self.address_bar.blockSignals(True)
        idx = self.address_bar.findText(folder_path)
        if idx >= 0:
            self.address_bar.setCurrentIndex(idx)
        else:
            self.address_bar.insertItem(0, folder_path)
            self.address_bar.setCurrentIndex(0)
        self.address_bar.blockSignals(False)
        add_address_folder(folder_path)
        set_last_folder(folder_path)

        if not add_to_navigation_history:
            return
        if self.navigation_index >= 0 and self.navigation_history[self.navigation_index] == folder_path:
            return
        if self.navigation_index < len(self.navigation_history) - 1:
            self.navigation_history = self.navigation_history[:self.navigation_index + 1]
        self.navigation_history.append(folder_path)
        self.navigation_history = self.navigation_history[-100:]
        self.navigation_index = len(self.navigation_history) - 1

    def on_quick_access_clicked(self, item):
        self.quick_access_list.viewport().repaint()
        path = self.quick_access_path(item.text())
        if path and os.path.exists(path):
            self.navigate_to_folder(path)

    def quick_access_path(self, name):
        home = os.path.expanduser("~")
        path_map = {
            "Desktop": os.path.join(home, "Desktop"),
            "Documents": os.path.join(home, "Documents"),
            "Downloads": os.path.join(home, "Downloads"),
            "Pictures": os.path.join(home, "Pictures"),
            "Videos": os.path.join(home, "Videos")
        }
        return path_map.get(name)

    def show_quick_access_context_menu(self, pos):
        item = self.quick_access_list.itemAt(pos)
        if not item:
            return
        folder_path = self.quick_access_path(item.text())
        if not folder_path:
            return

        menu = QMenu(self)
        open_action = QAction("Open in File Explorer", self)
        open_action.triggered.connect(
            lambda: self.open_folder_in_file_explorer(folder_path)
        )
        menu.addAction(open_action)
        menu.exec(self.quick_access_list.viewport().mapToGlobal(pos))

    def load_favorites_list(self):
        self.favorites_list.clear()
        for folder_path in get_favorite_folders():
            name = self.favorite_display_name(folder_path)
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, folder_path)
            item.setToolTip(folder_path)
            self.favorites_list.addItem(item)

    def favorite_display_name(self, folder_path):
        custom_name = get_favorite_display_name(folder_path)
        if custom_name:
            return custom_name
        path = folder_path.rstrip("\\/")
        name = os.path.basename(path)
        return name or folder_path

    def on_favorite_clicked(self, item):
        self.favorites_list.viewport().repaint()
        folder_path = item.data(Qt.ItemDataRole.UserRole)
        if folder_path and os.path.isdir(folder_path):
            self.navigate_to_folder(folder_path)
        elif folder_path:
            QMessageBox.warning(self, "Favorite", f"Favorite folder does not exist:\n\n{folder_path}")

    def add_folder_to_favorites(self, folder_path):
        if not folder_path or not os.path.isdir(folder_path):
            return
        add_favorite_folder(folder_path)
        if (
            self.current_folder_path and
            os.path.normcase(os.path.abspath(self.current_folder_path)) ==
            os.path.normcase(os.path.abspath(folder_path))
        ):
            set_favorite_sort_setting(folder_path, self.sort_key, self.sort_reverse)
        self.load_favorites_list()

    def show_favorites_context_menu(self, pos):
        item = self.favorites_list.itemAt(pos)
        if not item:
            return
        folder_path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        open_action = QAction("Open in File Explorer", self)
        open_action.triggered.connect(
            lambda: self.open_folder_in_file_explorer(folder_path)
        )
        menu.addAction(open_action)
        menu.addSeparator()

        rename_action = QAction("Rename Display Name...", self)
        rename_action.triggered.connect(lambda: self.rename_favorite_display_name(item))
        menu.addAction(rename_action)

        remove_action = QAction("Remove from Favorites", self)
        remove_action.triggered.connect(lambda: self.remove_folder_from_favorites(folder_path))
        menu.addAction(remove_action)
        menu.exec(self.favorites_list.viewport().mapToGlobal(pos))

    def rename_favorite_display_name(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename Favorite",
            "Display name:",
            text=item.text(),
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Favorite", "The display name cannot be empty.")
            return
        set_favorite_display_name(folder_path, name)
        self.load_favorites_list()

    def remove_folder_from_favorites(self, folder_path):
        remove_favorite_folder(folder_path)
        self.load_favorites_list()

    def show_tree_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid():
            return
        folder_path = self.file_model.filePath(index)
        if not os.path.isdir(folder_path):
            return

        menu = QMenu(self)
        open_action = QAction("Open in File Explorer", self)
        open_action.triggered.connect(
            lambda: self.open_folder_in_file_explorer(folder_path)
        )
        menu.addAction(open_action)

        add_action = QAction("Add to Favorites", self)
        add_action.triggered.connect(lambda: self.add_folder_to_favorites(folder_path))
        menu.addAction(add_action)
        menu.exec(self.tree_view.viewport().mapToGlobal(pos))

    def create_folder_in_current_folder(self):
        if not self.current_folder_path or not os.path.isdir(self.current_folder_path):
            return
        name, ok = QInputDialog.getText(self, "Create Folder", "Folder name:")
        if not ok:
            return
        name = name.strip().replace("/", "").replace("\\", "")
        if not name:
            QMessageBox.warning(self, "Create Folder", "Invalid folder name.")
            return
        folder_path = os.path.join(self.current_folder_path, name)
        if os.path.exists(folder_path):
            QMessageBox.warning(self, "Create Folder", "A file or folder with that name already exists.")
            return
        try:
            os.makedirs(folder_path)
        except OSError as e:
            QMessageBox.warning(self, "Create Folder", f"Failed to create folder:\n\n{e}")
            return
        self.add_thumbnail_paths([folder_path], keep_selection_path=folder_path)

    def copy_dropped_files_to_current_folder(self, paths):
        if not self.current_folder_path or not os.path.isdir(self.current_folder_path):
            QMessageBox.warning(self, "Drop Files", "Open a destination folder first.")
            return
        self.transfer_files_to_folder(paths, self.current_folder_path, move_files=False)

    def drop_paths_from_event(self, event):
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile()
            if path:
                paths.append(path)
        return paths

    def event_keyboard_modifiers(self, event):
        if hasattr(event, "modifiers"):
            return event.modifiers()
        if hasattr(event, "keyboardModifiers"):
            return event.keyboardModifiers()
        return Qt.KeyboardModifier.NoModifier

    def tree_drop_folder(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.tree_view.indexAt(pos)
        if not index.isValid():
            return None
        folder_path = self.file_model.filePath(index)
        return folder_path if os.path.isdir(folder_path) else None

    def thumbnail_drop_folder(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.thumbnail_view.indexAt(pos)
        if not index.isValid() or index.data(KIND_ROLE) != "folder":
            return None
        folder_path = index.data(PATH_ROLE)
        return folder_path if folder_path and os.path.isdir(folder_path) else None

    def drop_action_for_paths(self, paths, destination_folder, modifiers):
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            return Qt.DropAction.CopyAction
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return Qt.DropAction.MoveAction

        destination_drive = os.path.splitdrive(os.path.abspath(destination_folder))[0].lower()
        source_drives = {
            os.path.splitdrive(os.path.abspath(path))[0].lower()
            for path in paths
            if path
        }
        if source_drives and len(source_drives) == 1 and destination_drive in source_drives:
            return Qt.DropAction.MoveAction
        return Qt.DropAction.CopyAction

    def transfer_files_to_folder(self, paths, destination_folder, move_files=False):
        if not destination_folder or not os.path.isdir(destination_folder):
            return []

        copied_paths = []
        successful_sources = []
        failed_paths = []
        destination = os.path.abspath(destination_folder)
        video_decoder_stopped = self.pause_file_access(paths) if move_files else False
        try:
            source_paths = [
                source_path
                for source_path in paths
                if os.path.exists(source_path)
                and os.path.abspath(os.path.dirname(source_path)) != destination
            ]
            destinations = {
                source_path: os.path.join(destination_folder, os.path.basename(source_path))
                for source_path in source_paths
            }
            existed_before = {
                source_path: os.path.exists(target_path)
                for source_path, target_path in destinations.items()
            }

            if source_paths:
                operation = move_files_batch if move_files else copy_files_batch
                result = operation(source_paths, destination_folder)

                if move_files:
                    successful_sources = [
                        source_path
                        for source_path in source_paths
                        if not os.path.exists(source_path)
                        and os.path.exists(destinations[source_path])
                    ]
                elif result is True:
                    # A completed Shell operation also includes files the user
                    # deliberately skipped because their destinations existed.
                    successful_sources = [
                        source_path
                        for source_path in source_paths
                        if os.path.exists(destinations[source_path])
                    ]
                else:
                    # On cancellation or an error, retain any newly copied files
                    # without treating an already-existing destination as success.
                    successful_sources = [
                        source_path
                        for source_path in source_paths
                        if not existed_before[source_path]
                        and os.path.exists(destinations[source_path])
                    ]

                copied_paths = [destinations[source_path] for source_path in successful_sources]
                if result is False:
                    failed_paths = [
                        source_path
                        for source_path in source_paths
                        if source_path not in successful_sources
                    ]

            keep_selection_path = copied_paths[0] if copied_paths else self.current_image_path
            current_folder = os.path.abspath(self.current_folder_path) if self.current_folder_path else ""
            source_folders = {
                os.path.abspath(os.path.dirname(path))
                for path in paths
                if path
            }
            if copied_paths and current_folder == destination:
                self.add_thumbnail_paths(copied_paths, keep_selection_path=keep_selection_path)
            if move_files and successful_sources and current_folder in source_folders:
                self.remove_thumbnail_paths(
                    successful_sources, keep_selection_path=self.current_image_path
                )
        finally:
            if move_files:
                self.resume_file_access(video_decoder_stopped)
        if failed_paths:
            action = "move" if move_files else "copy"
            QMessageBox.warning(self, "File Transfer", f"Failed to {action} {len(failed_paths)} item(s).")
        return copied_paths

    def transfer_dialog_parent(self):
        if (
            hasattr(self, "fullscreen_viewer") and
            self.fullscreen_viewer.isVisible()
        ):
            return self.fullscreen_viewer
        return self

    def queue_transfer_files_to_folder(self, paths, destination_folder,
                                       move_files=False, context=None):
        if not paths or not destination_folder:
            return None
        return self.transfer_coordinator.enqueue(
            list(paths),
            destination_folder,
            move_files=move_files,
            context=context,
        )

    def execute_queued_transfer(self, plan, resolved_transfers):
        if not resolved_transfers:
            return {
                "copied_paths": [],
                "successful_sources": [],
                "failed": list(plan.missing_sources),
            }

        move_files = plan.job.move_files
        successful_sources = []
        copied_paths = []
        failed_paths = list(plan.missing_sources)
        cancelled = False
        video_decoder_stopped = self.pause_file_access(
            [item.source for item in resolved_transfers]
        ) if move_files else False
        try:
            owner = self.transfer_dialog_parent()
            owner_hwnd = self.shell_owner_handle(owner)
            operation = move_file_pairs if move_files else copy_file_pairs
            for overwrite in (False, True):
                group = [
                    item for item in resolved_transfers
                    if item.replace == overwrite
                ]
                if not group:
                    continue
                existed_before = {
                    item.source: os.path.exists(item.target) for item in group
                }
                result = operation(
                    [(item.source, item.target) for item in group],
                    overwrite=overwrite,
                    owner_hwnd=owner_hwnd,
                )
                if result is None:
                    cancelled = True

                for item in group:
                    if move_files:
                        succeeded = (
                            not os.path.exists(item.source) and
                            os.path.exists(item.target)
                        )
                    elif result is True:
                        succeeded = True
                    else:
                        succeeded = (
                            not existed_before[item.source] and
                            os.path.exists(item.target)
                        )
                    if succeeded:
                        successful_sources.append(item.source)
                        copied_paths.append(item.target)
                    elif result is False:
                        failed_paths.append(item.source)

            keep_selection_path = self.current_image_path or (
                copied_paths[0] if copied_paths else None
            )
            current_folder = (
                os.path.abspath(self.current_folder_path)
                if self.current_folder_path else ""
            )
            destination = os.path.abspath(plan.job.destination)
            source_folders = {
                os.path.abspath(os.path.dirname(path))
                for path in successful_sources
            }
            if copied_paths and current_folder == destination:
                self.add_thumbnail_paths(
                    copied_paths,
                    keep_selection_path=keep_selection_path,
                )
            if move_files and successful_sources and current_folder in source_folders:
                self.remove_thumbnail_paths(
                    successful_sources,
                    keep_selection_path=self.current_image_path,
                )
        finally:
            if move_files:
                self.resume_file_access(video_decoder_stopped)

        if failed_paths and not cancelled:
            action = "move" if move_files else "copy"
            QMessageBox.warning(
                self.transfer_dialog_parent(),
                "File Transfer",
                f"Failed to {action} {len(failed_paths)} item(s).",
            )
        return {
            "copied_paths": copied_paths,
            "successful_sources": successful_sources,
            "failed": failed_paths,
            "cancelled": cancelled,
        }

    def on_queued_transfer_finished(self, job, result):
        if not job.move_files:
            return
        successful_sources = set(result.get("successful_sources", []))
        fullscreen_source = job.context.get("fullscreen_source")
        if not fullscreen_source or fullscreen_source not in successful_sources:
            return
        if not self.fullscreen_viewer.isVisible():
            return
        if self.fullscreen_viewer.current_image_path != fullscreen_source:
            return

        fullscreen_target = job.context.get("fullscreen_target")
        if fullscreen_target and os.path.isfile(fullscreen_target):
            self.fullscreen_start_path = fullscreen_target
            self.current_image_path = fullscreen_target
            self.current_item_kind = "image"
            self.select_image_by_path(fullscreen_target)
            self.fullscreen_viewer.load_image(fullscreen_target)
        else:
            self.fullscreen_viewer.close()

    def refresh_folder(self):
        self.refresh_drive_buttons()
        selection = self.tree_view.selectionModel().selectedIndexes()
        if self.current_folder_path:
            self.load_current_folder(keep_selection_path=self.current_image_path)
        elif selection:
            self.on_folder_selected(selection[0])

    @staticmethod
    def drive_key_for_path(path):
        if not path:
            return ""
        absolute_path = os.path.abspath(path)
        drive, _ = os.path.splitdrive(absolute_path)
        if drive:
            return os.path.normcase(drive)
        if absolute_path.startswith(os.path.sep):
            return os.path.sep
        return ""

    def refresh_drive_buttons(self):
        while self.drive_buttons_layout.count():
            item = self.drive_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.drive_buttons = {}
        for drive_info in QDir.drives():
            root_path = drive_info.absoluteFilePath()
            drive, _ = os.path.splitdrive(root_path)
            label = drive.rstrip(":") if drive else QDir.toNativeSeparators(root_path)

            button = QToolButton(self.drive_buttons_widget)
            button.setText(label)
            button.setCheckable(True)
            button.setAutoRaise(False)
            button_font = QFont(button.font())
            if button_font.pointSizeF() > 0:
                button_font.setPointSizeF(max(7.0, button_font.pointSizeF() - 1.0))
            button.setFont(button_font)
            button.setFixedSize(
                max(16, button.fontMetrics().horizontalAdvance(label) + 7),
                22,
            )
            button.setToolTip(QDir.toNativeSeparators(root_path))
            button.setAccessibleName(f"Drive {label}")
            button.clicked.connect(
                lambda checked=False, path=root_path: self.navigate_to_folder(path)
            )
            self.drive_buttons_layout.addWidget(button)
            self.drive_buttons[self.drive_key_for_path(root_path)] = button

        self.update_drive_button_selection(
            getattr(self, "current_folder_path", None)
        )
        QTimer.singleShot(0, self.update_visible_drive_buttons)

    def update_visible_drive_buttons(self):
        available_width = self.drive_buttons_widget.width()
        spacing = self.drive_buttons_layout.spacing()
        used_width = 0
        for button in self.drive_buttons.values():
            required_width = button.width() + (spacing if used_width else 0)
            visible = used_width + required_width <= available_width
            button.setHidden(not visible)
            if visible:
                used_width += required_width

    def update_drive_button_selection(self, folder_path):
        selected_key = self.drive_key_for_path(folder_path)
        for drive_key, button in self.drive_buttons.items():
            button.setChecked(drive_key == selected_key)

    def go_to_parent_folder(self):
        if self.focusWidget() == self.address_bar.lineEdit():
            return
        if not self.current_folder_path:
            return

        parent_path = os.path.dirname(os.path.abspath(self.current_folder_path))
        if parent_path == os.path.abspath(self.current_folder_path):
            return
        if not os.path.isdir(parent_path):
            return

        self.navigate_to_folder(parent_path)

    def go_back_folder(self):
        if self.navigation_index <= 0:
            return

        self.navigation_index -= 1
        folder_path = self.navigation_history[self.navigation_index]
        self.navigate_to_folder(folder_path, add_to_history=False)

    def go_forward_folder(self):
        if self.navigation_index >= len(self.navigation_history) - 1:
            return

        self.navigation_index += 1
        folder_path = self.navigation_history[self.navigation_index]
        self.navigate_to_folder(folder_path, add_to_history=False)

    def navigate_to_folder(self, folder_path, add_to_history=True):
        if not os.path.isdir(folder_path):
            return

        idx = self.file_model.index(folder_path)
        self._navigating_history = not add_to_history
        previous_index = self.tree_view.currentIndex()
        self.tree_view.setCurrentIndex(idx)
        self.tree_view.scrollTo(idx)
        if previous_index == idx:
            self.on_folder_selected(idx)
        self._navigating_history = False

    def on_address_entered(self):
        path = self.address_bar.currentText()
        if os.path.exists(path) and os.path.isdir(path):
            self.navigate_to_folder(path)
        else:
            QMessageBox.warning(self, "Invalid Path", "The specified folder does not exist.")
            
    def on_address_selected(self, index):
        path = self.address_bar.itemText(index)
        if os.path.exists(path) and os.path.isdir(path):
            self.navigate_to_folder(path)

    def on_folder_selected(self, index):
        folder_path = self.file_model.filePath(index)
        if os.path.isdir(folder_path):
            self.tree_view.viewport().repaint()
            self.restore_favorite_sort_setting(folder_path)
            self.current_folder_path = folder_path
            self.update_folder_window_title(folder_path)
            self.update_drive_button_selection(folder_path)
            self.load_current_folder()
            self.remember_folder(folder_path, add_to_navigation_history=not self._navigating_history)

    def restore_favorite_sort_setting(self, folder_path):
        setting = get_favorite_sort_setting(folder_path)
        if setting is None:
            return
        self.sort_key, self.sort_reverse = setting
        combo_index = next(
            (
                index for index in range(self.sort_combo.count())
                if self.sort_combo.itemData(index) == setting
            ),
            -1,
        )
        if combo_index >= 0 and combo_index != self.sort_combo.currentIndex():
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(combo_index)
            self.sort_combo.blockSignals(False)

    def on_sort_changed(self, index=None):
        sort_data = self.sort_combo.currentData()
        if sort_data:
            self.sort_key, self.sort_reverse = sort_data

        if self.current_folder_path:
            set_favorite_sort_setting(
                self.current_folder_path, self.sort_key, self.sort_reverse
            )
            self.load_current_folder(keep_selection_path=self.current_image_path)

    def on_filter_changed(self, text):
        self.thumbnail_view.set_filter_text(text)
        self.update_status_bar()

    def on_show_options_changed(self, checked=None):
        self.show_images = self.show_images_action.isChecked()
        self.show_pdfs = self.show_pdfs_action.isChecked()
        self.show_videos = self.show_videos_action.isChecked()
        self.show_folders = self.show_folders_action.isChecked()
        self._show_options_dirty = True
        if not self.show_menu.isVisible():
            QTimer.singleShot(0, self.apply_pending_show_options)

    def on_show_menu_hidden(self):
        QTimer.singleShot(0, self.apply_pending_show_options)

    def apply_pending_show_options(self):
        if not self._show_options_dirty:
            return
        self._show_options_dirty = False
        if self.current_folder_path:
            self.load_current_folder(keep_selection_path=self.current_image_path)

    def load_current_folder(self, keep_selection_path=None):
        if not self.current_folder_path:
            return

        self.update_folder_window_title()

        if hasattr(self, "crop_prefetch_service"):
            self.clear_viewer_prefetch()
        self.thumbnail_view.load_folder(
            self.current_folder_path,
            sort_key=self.sort_key,
            reverse=self.sort_reverse,
            show_images=self.show_images,
            show_pdfs=self.show_pdfs,
            show_videos=self.show_videos,
            show_folders=self.show_folders
        )
        self.thumbnail_view.set_filter_text(self.filter_edit.text())
        if keep_selection_path:
            self.select_image_by_path(keep_selection_path)
        self.update_status_bar()
            
    def prompt_save_changes(self):
        if not self.image_modified:
            return True

        if self._session_auto_save_edits:
            if self.save_modified_to_original():
                return True
            self._session_auto_save_edits = False
            return False
            
        msg = QMessageBox(self)
        msg.setWindowTitle("Save Changes?")
        msg.setText("You have unsaved changes. Do you want to save them?")
        
        save_btn = msg.addButton("&Save", QMessageBox.ButtonRole.AcceptRole)
        save_as_btn = msg.addButton("Save &As...", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("&Discard", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("&Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(save_btn)
        remember_check = QCheckBox("Don't ask again this session")
        msg.setCheckBox(remember_check)
        discard_shortcut = QShortcut(QKeySequence("D"), msg)
        discard_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        discard_shortcut.activated.connect(discard_btn.click)
        
        msg.exec()
        
        clicked = msg.clickedButton()
        if clicked == save_btn:
            completed = self.save_modified_to_original()
        elif clicked == save_as_btn:
            completed = False
            if self.current_image_path and self.modified_pixmap:
                folder, name = os.path.split(self.current_image_path)
                from PyQt6.QtWidgets import QFileDialog
                filters = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All Files (*)"
                new_path, _ = QFileDialog.getSaveFileName(self, "Save Image As", os.path.join(folder, "edited_" + name), filters)
                if new_path:
                    if not self.modified_pixmap.save(new_path, quality=-1):
                        QMessageBox.warning(self, "Error", "Failed to save the image to the specified path.")
                        return False
                else:
                    return False
            self.image_modified = False
            self.modified_pixmap = None
            completed = True
        elif clicked == discard_btn:
            self.image_modified = False
            self.modified_pixmap = None
            completed = True
        else:
            return False

        if completed and remember_check.isChecked():
            self._session_auto_save_edits = True
        return completed

    def save_modified_to_original(self):
        if not self.current_image_path or not self.modified_pixmap:
            self.image_modified = False
            self.modified_pixmap = None
            return True
        if not self.modified_pixmap.save(self.current_image_path, quality=-1):
            QMessageBox.warning(self, "Error", "Failed to save the image. Make sure it is not read-only.")
            return False
        saved_path = self.current_image_path
        self.image_modified = False
        self.modified_pixmap = None
        self.clear_viewer_prefetch()
        self.update_saved_thumbnail_item(saved_path)
        return True

    def on_thumbnail_selected(self, current, previous=None):
        if not current.isValid():
            if not self.image_modified:
                self.current_image_path = None
                self.preview_viewer.clear_image()
                self.current_item_kind = None
                self.update_status_bar()
            return

        self.thumbnail_view.viewport().repaint()

        if self.image_modified:
            if not self.prompt_save_changes():
                if previous and previous.isValid():
                    self.thumbnail_view.selectionModel().blockSignals(True)
                    self.thumbnail_view.selectionModel().setCurrentIndex(previous, self.thumbnail_view.selectionModel().SelectionFlag.ClearAndSelect)
                    self.thumbnail_view.selectionModel().blockSignals(False)
                return

        file_path = current.data(Qt.ItemDataRole.UserRole)
        item_kind = current.data(KIND_ROLE)
        self.current_image_path = file_path
        self.current_item_kind = item_kind
        if item_kind == "image":
            self.video_frame_grabber.stop()
            self.load_prefetched_preview(file_path)
        elif item_kind == "video":
            self.clear_viewer_prefetch()
            self.show_placeholder_preview("video")
            self.video_frame_grabber.grab(file_path)
        elif item_kind == "folder":
            self.clear_viewer_prefetch()
            self.video_frame_grabber.stop()
            self.show_placeholder_preview("folder")
        else:
            self.preview_viewer.clear_image()
        self.image_modified = False
        self.modified_pixmap = None
        self.update_status_bar()
        
    def open_current_thumbnail_fullscreen(self):
        self.open_thumbnail_fullscreen(self.thumbnail_view.currentIndex())

    def open_thumbnail_fullscreen(self, index):
        file_path = index.data(PATH_ROLE)
        item_kind = index.data(KIND_ROLE)
        if not file_path:
            return

        if item_kind == "folder":
            self.open_folder_path(file_path)
        elif item_kind == "video":
            self.open_in_associated_program(file_path)
        elif item_kind == "image":
            self.fullscreen_start_path = file_path
            self.current_image_path = file_path
            self.current_item_kind = item_kind
            self.load_prefetched_fullscreen(file_path)
            
    def navigate_fullscreen(self, direction):
        model = self.thumbnail_view.model()
        if model.rowCount() == 0:
            return False
            
        current_path = self.fullscreen_viewer.current_image_path
        current_index = self.row_for_path(current_path)
        if current_index is None:
            current_index = self.thumbnail_view.first_visible_row()
            if current_index is None:
                return False
                
        if direction == 1:
            current_index = self.next_visible_image_row(current_index, 1, wrap=False)
        elif direction == -1:
            current_index = self.next_visible_image_row(current_index, -1, wrap=False)
        elif direction == 'first':
            current_index = self.first_visible_image_row()
        elif direction == 'last':
            current_index = self.last_visible_image_row()
        if current_index is None:
            return False

        new_path = model.item(current_index).data(PATH_ROLE)
        if new_path == current_path:
            return False
        if not self.prompt_save_changes():
            return False

        self.current_image_path = new_path
        self.current_item_kind = "image"
        self.load_prefetched_fullscreen(new_path)
        return True

    def fullscreen_image_paths(self):
        model = self.thumbnail_view.model()
        paths = []
        for row in range(model.rowCount()):
            item = model.item(row)
            if (
                item and
                not self.thumbnail_view.isRowHidden(row) and
                item.data(KIND_ROLE) == "image"
            ):
                path = item.data(PATH_ROLE)
                if path:
                    paths.append(path)
        return paths

    def navigate_fullscreen_to_path(self, file_path):
        if not file_path or file_path == self.fullscreen_viewer.current_image_path:
            return False
        row = self.row_for_path(file_path)
        if row is None or self.thumbnail_view.isRowHidden(row):
            return False
        item = self.thumbnail_view.model().item(row)
        if item is None or item.data(KIND_ROLE) != "image":
            return False
        if not self.prompt_save_changes():
            return False
        self.current_image_path = file_path
        self.current_item_kind = "image"
        self.load_prefetched_fullscreen(file_path)
        return True

    def leave_fullscreen(self, commit_current):
        if not self.prompt_save_changes():
            return False

        target_path = self.fullscreen_viewer.current_image_path if commit_current else self.fullscreen_start_path
        if target_path:
            self.select_image_by_path(target_path)
        self.fullscreen_start_path = None
        return True

    def select_image_by_path(self, file_path, update_preview=True):
        item = self.thumbnail_view.item_for_path(file_path)
        if item is None:
            return
        model = self.thumbnail_view.model()
        index = model.indexFromItem(item)
        if not index.isValid():
            return

        selection_model = self.thumbnail_view.selectionModel()
        changed = self.thumbnail_view.currentIndex() != index
        if changed and not update_preview:
            selection_model.blockSignals(True)
            self.thumbnail_view.setCurrentIndex(index)
            selection_model.blockSignals(False)
        elif changed:
            self.thumbnail_view.setCurrentIndex(index)

        self.current_image_path = file_path
        self.current_item_kind = index.data(KIND_ROLE)
        self.thumbnail_view.prioritize_rows_around(index.row())
        self.update_status_bar()

    def row_for_path(self, file_path):
        item = self.thumbnail_view.item_for_path(file_path)
        return item.row() if item is not None else None

    def get_adjacent_image_path(self, file_path, direction):
        row = self.row_for_path(file_path)
        if row is None:
            return None

        adjacent_row = self.next_visible_image_row(row, direction)
        if adjacent_row is None:
            return None

        item = self.thumbnail_view.model().item(adjacent_row)
        return item.data(PATH_ROLE) if item else None

    def next_visible_image_row(self, row, direction, wrap=True):
        model = self.thumbnail_view.model()
        count = model.rowCount()
        if count == 0 or direction not in (-1, 1):
            return None

        if wrap:
            candidates = (
                (row + (step * direction)) % count
                for step in range(1, count + 1)
            )
        else:
            stop = count if direction > 0 else -1
            candidates = range(row + direction, stop, direction)

        for candidate in candidates:
            item = model.item(candidate)
            if item and not self.thumbnail_view.isRowHidden(candidate) and item.data(KIND_ROLE) == "image":
                return candidate
        return None

    def first_visible_image_row(self):
        model = self.thumbnail_view.model()
        for row in range(model.rowCount()):
            item = model.item(row)
            if item and not self.thumbnail_view.isRowHidden(row) and item.data(KIND_ROLE) == "image":
                return row
        return None

    def last_visible_image_row(self):
        model = self.thumbnail_view.model()
        for row in range(model.rowCount() - 1, -1, -1):
            item = model.item(row)
            if item and not self.thumbnail_view.isRowHidden(row) and item.data(KIND_ROLE) == "image":
                return row
        return None

    def open_folder_path(self, folder_path):
        if not os.path.isdir(folder_path):
            return
        self.navigate_to_folder(folder_path)

    def open_folder_in_file_explorer(self, folder_path):
        if not folder_path or not os.path.isdir(folder_path):
            QMessageBox.warning(
                self,
                "Open Folder",
                "The selected folder no longer exists.",
            )
            return False

        success = QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.abspath(folder_path))
        )
        if not success:
            QMessageBox.warning(
                self,
                "Open Folder",
                "The folder could not be opened in the system file manager.",
            )
        return bool(success)

    def selected_file_paths(self):
        paths = []
        indexes = sorted(
            self.thumbnail_view.selectionModel().selectedIndexes(),
            key=lambda index: index.row()
        )
        for index in indexes:
            if not index.isValid() or index.data(KIND_ROLE) == "folder":
                continue
            path = index.data(PATH_ROLE)
            if path and path not in paths:
                paths.append(path)
        return paths

    def selected_clipboard_paths(self):
        focus_widget = QApplication.focusWidget()
        tree_has_focus = (
            focus_widget is self.tree_view or
            (focus_widget is not None and self.tree_view.isAncestorOf(focus_widget))
        )
        if tree_has_focus:
            tree_paths = self.selected_tree_folder_paths()
            if tree_paths:
                return tree_paths

        paths = []
        indexes = sorted(
            self.thumbnail_view.selectionModel().selectedIndexes(),
            key=lambda index: index.row()
        )
        for index in indexes:
            if not index.isValid():
                continue
            path = index.data(PATH_ROLE)
            if path and os.path.exists(path) and path not in paths:
                paths.append(path)
        if paths:
            return paths

        if self.current_image_path and os.path.exists(self.current_image_path):
            return [self.current_image_path]
        return self.selected_tree_folder_paths()

    def selected_tree_folder_paths(self):
        selection_model = self.tree_view.selectionModel()
        indexes = selection_model.selectedRows(0) if selection_model else []
        if not indexes and self.tree_view.currentIndex().isValid():
            indexes = [self.tree_view.currentIndex()]

        paths = []
        for index in indexes:
            path = self.file_model.filePath(index)
            if path and os.path.isdir(path) and path not in paths:
                paths.append(path)
        return paths

    def selected_image_paths(self):
        paths = []
        indexes = sorted(
            self.thumbnail_view.selectionModel().selectedIndexes(),
            key=lambda index: index.row()
        )
        for index in indexes:
            if not index.isValid() or index.data(KIND_ROLE) != "image":
                continue
            path = index.data(PATH_ROLE)
            if path and path not in paths:
                paths.append(path)
        return paths

    def supports_associated_editor(self):
        return windows_shell.is_windows()

    def open_in_associated_program(self, file_path=None, parent_override=None):
        path = file_path or self.current_image_path
        if not path or not os.path.isfile(path):
            return False

        parent = parent_override or self
        if windows_shell.is_windows():
            success, error = windows_shell.open_associated_file(
                path, verb="open", owner_hwnd=self.shell_owner_handle(parent)
            )
        else:
            success = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            error = "No application is associated with this file type."
        if not success:
            QMessageBox.warning(parent, "Open File", error)
        return bool(success)

    def open_in_associated_editor(self, file_path=None, parent_override=None):
        if not windows_shell.is_windows():
            return False
        path = file_path or self.current_image_path
        if not path or not os.path.isfile(path):
            return False

        parent = parent_override or self
        success, error = windows_shell.open_associated_file(
            path, verb="edit", owner_hwnd=self.shell_owner_handle(parent)
        )
        if not success:
            QMessageBox.warning(parent, "Open in Editor", error)
        return bool(success)

    def print_image(self, file_path=None, parent_override=None):
        if not windows_shell.is_windows():
            return False
        path = file_path or self.current_image_path
        parent = parent_override or self
        if not path or not os.path.isfile(path):
            return False
        if path == self.current_image_path and self.image_modified:
            if not self.prompt_save_changes():
                return False

        success, error = windows_shell.print_file(
            path, owner_hwnd=self.shell_owner_handle(parent)
        )
        if not success:
            QMessageBox.warning(parent, "Print", error)
        return bool(success)

    def set_image_as_wallpaper(self, file_path=None, parent_override=None):
        if not windows_shell.is_windows():
            return False
        path = file_path or self.current_image_path
        parent = parent_override or self
        if not path or not os.path.isfile(path):
            return False
        if path == self.current_image_path and self.image_modified:
            if not self.prompt_save_changes():
                return False

        success, error = windows_shell.set_desktop_wallpaper(path)
        if not success:
            QMessageBox.warning(parent, "Desktop Wallpaper", error)
        return bool(success)

    def shell_owner_handle(self, parent=None):
        try:
            return int((parent or self).winId())
        except (AttributeError, TypeError, RuntimeError):
            return 0

    def add_open_with_menu(self, menu, file_path, parent_override=None):
        if not file_path or not os.path.isfile(file_path):
            return None

        open_menu = menu.addMenu("Open with")
        program_action = QAction("Associated program\tF3", open_menu)
        program_action.triggered.connect(
            lambda checked=False, path=file_path: self.open_in_associated_program(
                path, parent_override=parent_override
            )
        )
        open_menu.addAction(program_action)

        if windows_shell.is_windows():
            editor_action = QAction("Associated editor\tF4", open_menu)
            editor_action.triggered.connect(
                lambda checked=False, path=file_path: self.open_in_associated_editor(
                    path, parent_override=parent_override
                )
            )
            open_menu.addAction(editor_action)
        return open_menu

    def add_windows_image_actions(self, menu, file_path, parent_override=None):
        if (
            not windows_shell.is_windows() or
            not file_path or
            not os.path.isfile(file_path)
        ):
            return []

        print_action = QAction("Print", menu)
        print_action.triggered.connect(
            lambda checked=False, path=file_path: self.print_image(
                path, parent_override=parent_override
            )
        )
        menu.addAction(print_action)

        wallpaper_action = QAction("Set as Desktop Wallpaper", menu)
        wallpaper_action.triggered.connect(
            lambda checked=False, path=file_path: self.set_image_as_wallpaper(
                path, parent_override=parent_override
            )
        )
        menu.addAction(wallpaper_action)
        return [print_action, wallpaper_action]

    def add_send_to_menu(self, menu, file_paths, parent_override=None):
        if not windows_shell.is_windows():
            return None

        paths = [path for path in file_paths if path and os.path.isfile(path)]
        send_menu = menu.addMenu("Send To")
        targets = windows_shell.list_send_to_targets()
        if not paths or not targets:
            empty_action = QAction("No compatible targets", send_menu)
            empty_action.setEnabled(False)
            send_menu.addAction(empty_action)
            return send_menu

        icon_provider = QFileIconProvider()
        for target in targets:
            action = QAction(
                icon_provider.icon(QFileInfo(target.path)),
                target.display_name,
                send_menu,
            )
            action.triggered.connect(
                lambda checked=False, send_target=target, selected_paths=tuple(paths):
                    self.send_files_to_target(
                        send_target,
                        selected_paths,
                        parent_override=parent_override,
                    )
            )
            send_menu.addAction(action)
        return send_menu

    def send_files_to_target(self, target, file_paths, parent_override=None):
        parent = parent_override or self
        if not target or not os.path.exists(target.path):
            QMessageBox.warning(parent, "Send To", "The selected Send To target no longer exists.")
            return False

        paths = [path for path in file_paths if path and os.path.isfile(path)]
        if not paths:
            QMessageBox.warning(parent, "Send To", "None of the selected files still exist.")
            return False

        if target.kind == "folder":
            self.transfer_files_to_folder(paths, target.path, move_files=False)
            return True

        success, error = windows_shell.launch_send_to_target(
            target, paths, owner_hwnd=self.shell_owner_handle(parent)
        )
        if not success:
            QMessageBox.warning(parent, "Send To", error)
        return bool(success)

    def delete_selected_files(self, paths=None, permanent=False, stay_fullscreen=False):
        if paths is None:
            paths = self.selected_file_paths()
        else:
            paths = [path for path in paths if path]
        if not paths:
            return

        fullscreen_visible = hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible()
        fullscreen_target_path = None
        if stay_fullscreen and fullscreen_visible:
            fullscreen_current_path = self.fullscreen_viewer.current_image_path
            fullscreen_target_path = self.get_adjacent_image_path(fullscreen_current_path, 1)
            if fullscreen_target_path in paths:
                fullscreen_target_path = self.get_adjacent_image_path(fullscreen_current_path, -1)
            if fullscreen_target_path in paths:
                fullscreen_target_path = None

        action_text = "permanently delete" if permanent else "move to the Recycle Bin"
        if len(paths) == 1:
            message = f"{action_text.capitalize()} this file?\n\n{os.path.basename(paths[0])}"
        else:
            message = f"{action_text.capitalize()} {len(paths)} selected files?"

        reply = QMessageBox.question(
            self,
            "Delete",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        video_decoder_stopped = self.pause_file_access(paths)

        try:
            if delete_files(paths, permanent=permanent):
                self.image_modified = False
                self.modified_pixmap = None
                keep_selection_path = fullscreen_target_path if stay_fullscreen else None
                self.remove_thumbnail_paths(paths, keep_selection_path=keep_selection_path)

                if stay_fullscreen and fullscreen_visible and fullscreen_target_path and os.path.exists(fullscreen_target_path):
                    self.current_image_path = fullscreen_target_path
                    self.current_item_kind = "image"
                    self.preview_viewer.load_image(fullscreen_target_path)
                    self.fullscreen_viewer.load_image(fullscreen_target_path)
                    self.fullscreen_viewer.refocus()
                elif fullscreen_visible:
                    self.fullscreen_viewer.close()
            else:
                QMessageBox.warning(self, "Delete", "Failed to delete the selected file(s).")
        finally:
            self.resume_file_access(video_decoder_stopped)

    def pause_file_access(self, paths):
        selected_videos = False
        for path in paths:
            item = self.thumbnail_view.item_for_path(path)
            if item is not None and item.data(KIND_ROLE) == "video":
                selected_videos = True
                break
        self.clear_viewer_prefetch()
        self.thumbnail_view.set_background_activity_paused(True)
        if selected_videos:
            self.video_frame_grabber.shutdown()
        return selected_videos

    def resume_file_access(self, video_decoder_stopped):
        self.thumbnail_view.set_background_activity_paused(False)
        if video_decoder_stopped:
            self.restart_video_thumbnail_queue()

    def restart_video_thumbnail_queue(self):
        if not self.show_videos:
            return
        video_paths = [
            record[0] for record in self.thumbnail_view.files
            if record[4] == "video" and os.path.isfile(record[0])
        ]
        self.video_frame_grabber.set_thumbnail_queue(
            self.thumbnail_view.load_generation, video_paths
        )
        if (
            self.current_item_kind == "video" and
            self.current_image_path in video_paths
        ):
            self.video_frame_grabber.grab(self.current_image_path)

    def show_placeholder_preview(self, kind):
        icon = self.thumbnail_view.video_icon if kind == "video" else self.thumbnail_view.folder_icon
        self.preview_viewer.set_pixmap(icon.pixmap(300, 300))

    def on_video_frame_ready(self, file_path, image):
        if self.current_image_path != file_path or self.current_item_kind != "video":
            return
        self.preview_viewer.set_pixmap(QPixmap.fromImage(image))

    def on_video_thumbnail_ready(self, generation, file_path, image):
        self.thumbnail_view.update_video_thumbnail(generation, file_path, image)

    def load_prefetched_preview(self, file_path):
        image = self.take_viewer_prefetch(file_path)
        if image is not None:
            self.preview_viewer.set_pixmap(QPixmap.fromImage(image))
        else:
            self.preview_viewer.load_image(file_path)
        self.schedule_viewer_prefetch(file_path)

    def load_prefetched_fullscreen(self, file_path):
        image = self.take_viewer_prefetch(file_path)
        self.fullscreen_viewer.load_image(file_path, image)
        self.schedule_viewer_prefetch(file_path)

    def schedule_viewer_prefetch(self, file_path):
        row = self.row_for_path(file_path)
        if row is None:
            return
        paths = []
        forward_row = row
        backward_row = row
        for _ in range(2):
            forward_row = self.next_visible_image_row(forward_row, 1)
            if forward_row is not None:
                path = self.thumbnail_view.model().item(forward_row).data(PATH_ROLE)
                if path != file_path and path not in paths:
                    paths.append(path)
            backward_row = self.next_visible_image_row(backward_row, -1)
            if backward_row is not None:
                path = self.thumbnail_view.model().item(backward_row).data(PATH_ROLE)
                if path != file_path and path not in paths:
                    paths.append(path)
        self.viewer_prefetch_generation = self.crop_prefetch_service.request(paths)

    def on_viewer_prefetch_ready(self, generation, path, fingerprint, image, cost):
        if generation != self.viewer_prefetch_generation or image.isNull():
            return
        if self.file_fingerprint(path) != fingerprint:
            return

        existing = self.viewer_prefetch_cache.pop(path, None)
        if existing is not None:
            self.viewer_prefetch_cache_bytes -= existing[2]
        limit = self.crop_prefetch_service.memory_limit
        while self.viewer_prefetch_cache and self.viewer_prefetch_cache_bytes + cost > limit:
            _, (_, _, old_cost) = self.viewer_prefetch_cache.popitem(last=False)
            self.viewer_prefetch_cache_bytes -= old_cost
        if cost <= limit:
            self.viewer_prefetch_cache[path] = (fingerprint, image, cost)
            self.viewer_prefetch_cache_bytes += cost

    def take_viewer_prefetch(self, path):
        entry = self.viewer_prefetch_cache.pop(path, None)
        if entry is None:
            return None
        fingerprint, image, cost = entry
        self.viewer_prefetch_cache_bytes = max(0, self.viewer_prefetch_cache_bytes - cost)
        if fingerprint != self.file_fingerprint(path):
            return None
        return image

    def clear_viewer_prefetch(self):
        self.crop_prefetch_service.cancel()
        self.viewer_prefetch_generation = self.crop_prefetch_service.generation
        self.viewer_prefetch_cache.clear()
        self.viewer_prefetch_cache_bytes = 0

    def file_fingerprint(self, path):
        try:
            stat = os.stat(path)
            return (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return None

    def update_status_bar(self):
        if not self.thumbnail_view.model():
            self.status_label.clear()
            return

        model = self.thumbnail_view.model()
        total = model.rowCount()
        visible = self.thumbnail_view.visible_item_count
        selected_indexes = self.thumbnail_view.selectionModel().selectedIndexes()
        selected = len(selected_indexes)

        parts = [f"{visible} object(s)"]
        if visible != total:
            parts[0] += f" / {total} total"
        parts.append(f"{selected} selected")

        index = self.thumbnail_view.currentIndex()
        if index.isValid():
            path = index.data(PATH_ROLE)
            if path:
                parts.append(os.path.basename(path))

            width = index.data(WIDTH_ROLE)
            height = index.data(HEIGHT_ROLE)
            if width and height:
                parts.append(f"{width}x{height}")

            file_size = index.data(SIZE_ROLE)
            if file_size is not None:
                parts.append(self.format_file_size(file_size))

            modified = index.data(MODIFIED_ROLE)
            if modified:
                parts.append(datetime.fromtimestamp(modified).strftime("%d.%m.%Y - %H:%M:%S"))

        self.status_label.setText("   ".join(parts))

    def format_file_size(self, size):
        size = float(size or 0)
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        unit = 0
        while size >= 1024 and unit < len(units) - 1:
            size /= 1024.0
            unit += 1
        if unit == 0:
            return f"{int(size)} {units[unit]}"
        return f"{size:.2f} {units[unit]}"

    def file_operation_paths(self, parent_override=None):
        if (
            parent_override is self.fullscreen_viewer and
            self.fullscreen_viewer.current_image_path and
            os.path.isfile(self.fullscreen_viewer.current_image_path)
        ):
            return [self.fullscreen_viewer.current_image_path]

        paths = self.selected_file_paths()
        if paths:
            return paths
        if (
            self.current_image_path and
            self.current_item_kind != "folder" and
            os.path.isfile(self.current_image_path)
        ):
            return [self.current_image_path]
        return []
        
    def open_copy_dialog(self, parent_override=None):
        paths = self.file_operation_paths(parent_override)
        if not paths:
            return
        dlg = CopyMoveDialog(parent_override or self, is_move=False)
        if dlg.exec() and dlg.selected_folder:
            self.queue_transfer_files_to_folder(
                paths, dlg.selected_folder, move_files=False
            )
        self.refocus_fullscreen_if_visible(immediate=True)
             
    def open_move_dialog(self, parent_override=None):
        paths = self.file_operation_paths(parent_override)
        if not paths:
            return
        dlg = CopyMoveDialog(parent_override or self, is_move=True)
        if dlg.exec() and dlg.selected_folder:
            source_path = paths[0]
            fullscreen_visible = (
                len(paths) == 1 and
                hasattr(self, "fullscreen_viewer") and
                self.fullscreen_viewer.isVisible() and
                self.fullscreen_viewer.current_image_path == source_path
            )
            fullscreen_target = (
                self.get_adjacent_image_path(source_path, 1)
                if fullscreen_visible else None
            )
            context = {
                "fullscreen_source": source_path if fullscreen_visible else None,
                "fullscreen_target": fullscreen_target,
            }
            self.queue_transfer_files_to_folder(
                paths,
                dlg.selected_folder,
                move_files=True,
                context=context,
            )
        self.refocus_fullscreen_if_visible(immediate=True)

    def refocus_fullscreen_if_visible(self, immediate=False):
        if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
            if immediate:
                self.fullscreen_viewer.refocus()
            else:
                self.fullscreen_viewer.refocus_later()

    def on_crop_board_image_saved(self, file_path, update_viewers=True):
        self.current_image_path = file_path
        self.current_item_kind = "image"
        self.update_saved_thumbnail_item(file_path)
        if update_viewers:
            self.load_prefetched_preview(file_path)
        if update_viewers and hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
            self.fullscreen_viewer.load_image(file_path)

    def on_crop_board_image_changed(self, file_path, update_viewers=True):
        self.current_image_path = file_path
        self.current_item_kind = "image"
        self.select_image_by_path(file_path, update_preview=update_viewers)
        if update_viewers and hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
            self.fullscreen_viewer.load_image(file_path)

    @staticmethod
    def is_editable_image_path(file_path):
        return os.path.splitext(file_path or "")[1].lower() in EDITABLE_IMAGE_EXTENSIONS
            
    def open_crop_board(self, parent_override=None):
        if (
            self.current_image_path and
            self.current_item_kind == "image" and
            self.is_editable_image_path(self.current_image_path)
        ):
            if not parent_override and hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                parent_override = self.fullscreen_viewer
                
            navigation_paths = self.thumbnail_view.visible_image_paths(
                editable_only=True
            )
            self.clear_viewer_prefetch()
            self.thumbnail_view.set_background_activity_paused(True)
            try:
                dlg = CropBoard(
                    self.current_image_path,
                    parent_override or self,
                    adjacent_image_cb=self.get_adjacent_image_path,
                    navigation_paths=navigation_paths,
                    prefetch_service=self.crop_prefetch_service
                )
                dlg.image_saved.connect(lambda file_path: self.on_crop_board_image_saved(file_path, update_viewers=False))
                dlg.image_changed.connect(lambda file_path: self.on_crop_board_image_changed(file_path, update_viewers=False))
                accepted = dlg.exec()
            finally:
                self.thumbnail_view.set_background_activity_paused(False)
            if accepted or dlg.saved_any:
                self.current_image_path = dlg.image_path
                self.current_item_kind = "image"
                folder, _ = os.path.split(self.current_image_path)
                self.current_folder_path = folder
                self.select_image_by_path(self.current_image_path)
                self.load_prefetched_preview(self.current_image_path)
                if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                    self.fullscreen_viewer.load_image(self.current_image_path)
                    
            if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                self.fullscreen_viewer.showFullScreen()
                self.fullscreen_viewer.activateWindow()
                self.fullscreen_viewer.setFocus()

    def update_saved_thumbnail_item(self, file_path, request_refresh=True):
        item = self.thumbnail_view.item_for_path(file_path)
        if item is None:
            return

        _, name = os.path.split(file_path)
        _, ext = os.path.splitext(name)
        ext = ext[1:].lower()
        item.setData(ext, EXT_ROLE)
        try:
            stat = os.stat(file_path)
            item.setData(stat.st_size, SIZE_ROLE)
            item.setData(stat.st_mtime, MODIFIED_ROLE)
        except OSError:
            pass
        if request_refresh:
            self.thumbnail_view.request_thumbnail_refresh(file_path)
        self.update_status_bar()

    def restore_thumbnail_selection(self, paths, current_path=None):
        selection_model = self.thumbnail_view.selectionModel()
        selection_model.blockSignals(True)
        try:
            selection_model.clearSelection()
            valid_indexes = []
            for path in paths:
                item = self.thumbnail_view.item_for_path(path)
                if item is None:
                    continue
                index = self.thumbnail_view.model().indexFromItem(item)
                if not index.isValid():
                    continue
                selection_model.select(index, QItemSelectionModel.SelectionFlag.Select)
                valid_indexes.append(index)

            current_item = self.thumbnail_view.item_for_path(current_path) if current_path else None
            current_index = (
                self.thumbnail_view.model().indexFromItem(current_item)
                if current_item is not None
                else (valid_indexes[0] if valid_indexes else None)
            )
            if current_index is not None and current_index.isValid():
                selection_model.setCurrentIndex(
                    current_index,
                    QItemSelectionModel.SelectionFlag.NoUpdate
                )
        finally:
            selection_model.blockSignals(False)

        if current_path:
            item = self.thumbnail_view.item_for_path(current_path)
            if item is not None:
                self.thumbnail_view.prioritize_rows_around(item.row())
        self.update_status_bar()

    def reposition_thumbnail_items(self, paths):
        model = self.thumbnail_view.model()
        items = []
        for path in paths:
            item = self.thumbnail_view.item_for_path(path)
            if item is not None:
                items.append(item)
        if not items:
            return

        self.thumbnail_view.setUpdatesEnabled(False)
        try:
            for row in sorted((item.row() for item in items), reverse=True):
                model.takeRow(row)
            for item in items:
                model.insertRow(self.insertion_row_for_thumbnail_item(item), item)
        finally:
            self.thumbnail_view.setUpdatesEnabled(True)

    def add_thumbnail_paths(self, paths, keep_selection_path=None):
        added_paths = []
        new_image_paths = []
        new_video_paths = []
        for file_path in paths:
            if self.row_for_path(file_path) is not None:
                self.update_saved_thumbnail_item(file_path)
                added_paths.append(file_path)
                continue

            item = self.create_thumbnail_item(file_path)
            if item is None:
                continue
            row = self.insertion_row_for_thumbnail_item(item)
            self.thumbnail_view.model().insertRow(row, item)
            self.thumbnail_view.register_item(item)
            added_paths.append(file_path)
            if item.data(KIND_ROLE) == "image":
                new_image_paths.append(file_path)
            elif item.data(KIND_ROLE) == "video":
                new_video_paths.append(file_path)

        if added_paths:
            self.thumbnail_view.apply_filter()
            self.thumbnail_view.sync_worker_records()
            for file_path in new_image_paths:
                self.update_saved_thumbnail_item(file_path)
            self.thumbnail_view.request_video_thumbnails(new_video_paths)
        if keep_selection_path and self.row_for_path(keep_selection_path) is not None:
            self.select_image_by_path(keep_selection_path)
        elif added_paths:
            self.select_image_by_path(added_paths[0])
        self.update_status_bar()

    def remove_thumbnail_paths(self, paths, keep_selection_path=None):
        model = self.thumbnail_view.model()
        rows = []
        removed_set = set(paths)
        for path in paths:
            row = self.row_for_path(path)
            if row is not None:
                rows.append(row)
        if not rows:
            return

        first_removed_row = min(rows)
        for row in sorted(rows, reverse=True):
            item = model.item(row)
            if item is not None:
                self.thumbnail_view.unregister_path(item.data(PATH_ROLE))
            model.removeRow(row)
        self.thumbnail_view.apply_filter()
        self.thumbnail_view.sync_worker_records()

        if keep_selection_path and self.row_for_path(keep_selection_path) is not None:
            self.select_image_by_path(keep_selection_path)
        elif self.current_image_path in removed_set:
            self.select_nearby_thumbnail(first_removed_row)
        else:
            self.update_status_bar()

    def select_nearby_thumbnail(self, preferred_row):
        model = self.thumbnail_view.model()
        if model.rowCount() == 0:
            self.current_image_path = None
            self.current_item_kind = None
            self.preview_viewer.clear_image()
            self.update_status_bar()
            return

        row = min(preferred_row, model.rowCount() - 1)
        for candidate in range(row, model.rowCount()):
            if not self.thumbnail_view.isRowHidden(candidate):
                self.thumbnail_view.setCurrentIndex(model.index(candidate, 0))
                return
        for candidate in range(row - 1, -1, -1):
            if not self.thumbnail_view.isRowHidden(candidate):
                self.thumbnail_view.setCurrentIndex(model.index(candidate, 0))
                return

        self.current_image_path = None
        self.current_item_kind = None
        self.preview_viewer.clear_image()
        self.update_status_bar()

    def create_thumbnail_item(self, file_path):
        if not os.path.exists(file_path):
            return None

        record = self.thumbnail_record_for_path(file_path)
        if record is None:
            return None

        _, file_name, ext, modified_time, kind, file_size = record
        icon = self.thumbnail_view._icon_for_kind(kind)
        label = thumbnail_item_label(file_name, ext, kind, file_size)
        item = QStandardItem(icon, label)
        item.setData(file_path, PATH_ROLE)
        item.setData(kind, KIND_ROLE)
        item.setData(ext, EXT_ROLE)
        item.setData(file_size, SIZE_ROLE)
        item.setData(modified_time, MODIFIED_ROLE)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def thumbnail_record_for_path(self, file_path):
        file_name = os.path.basename(file_path)
        if os.path.isdir(file_path):
            if not self.show_folders:
                return None
            ext = ""
            kind = "folder"
        elif os.path.isfile(file_path):
            _, ext = os.path.splitext(file_name)
            ext = ext[1:].lower()
            if ext == "pdf" and self.show_pdfs:
                kind = "image"
            elif (
                ext != "pdf" and
                ext in self.thumbnail_view._supported_image_formats() and
                self.show_images
            ):
                kind = "image"
            elif ext in self.thumbnail_view._supported_video_formats() and self.show_videos:
                kind = "video"
            else:
                return None
        else:
            return None

        try:
            stat = os.stat(file_path)
            modified_time = stat.st_mtime
            file_size = stat.st_size
        except OSError:
            modified_time = 0
            file_size = 0
        return (file_path, file_name, ext, modified_time, kind, file_size)

    def insertion_row_for_thumbnail_item(self, new_item):
        model = self.thumbnail_view.model()
        for row in range(model.rowCount()):
            existing = model.item(row)
            if existing and self.thumbnail_item_before(new_item, existing):
                return row
        return model.rowCount()

    def thumbnail_item_before(self, left, right):
        left_kind = left.data(KIND_ROLE)
        right_kind = right.data(KIND_ROLE)
        if left_kind == "folder" and right_kind != "folder":
            return True
        if left_kind != "folder" and right_kind == "folder":
            return False

        left_name = os.path.basename(left.data(PATH_ROLE) or "").lower()
        right_name = os.path.basename(right.data(PATH_ROLE) or "").lower()
        if left_kind == "folder" and right_kind == "folder":
            return left_name < right_name

        if self.sort_key == "date":
            left_key = (left.data(MODIFIED_ROLE) or 0, left_name)
            right_key = (right.data(MODIFIED_ROLE) or 0, right_name)
        elif self.sort_key == "type":
            left_key = ((left.data(EXT_ROLE) or ""), left_name)
            right_key = ((right.data(EXT_ROLE) or ""), right_name)
        else:
            left_key = left_name
            right_key = right_name

        return left_key > right_key if self.sort_reverse else left_key < right_key
            
    def open_adjust_board(self, parent_override=None):
        if (
            self.current_image_path and
            self.current_item_kind == "image" and
            self.is_editable_image_path(self.current_image_path)
        ):
            if not parent_override and hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                parent_override = self.fullscreen_viewer
                
            from ui.adjust_board import AdjustBoard
            navigation_paths = self.thumbnail_view.visible_image_paths(
                editable_only=True
            )
            self.clear_viewer_prefetch()
            self.thumbnail_view.set_background_activity_paused(True)
            try:
                dlg = AdjustBoard(
                    self.current_image_path,
                    parent_override or self,
                    navigation_paths=navigation_paths,
                )
                dlg.image_saved.connect(self.on_adjust_board_image_saved)
                dlg.image_changed.connect(self.on_adjust_board_image_changed)
                dlg.exec()
            finally:
                self.thumbnail_view.set_background_activity_paused(False)

            final_path = dlg.image_path
            if final_path and os.path.isfile(final_path):
                self.current_image_path = final_path
                self.current_item_kind = "image"
                folder, _ = os.path.split(final_path)
                self.current_folder_path = folder
                self.select_image_by_path(final_path, update_preview=False)
                self.load_prefetched_preview(final_path)
                if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                    self.fullscreen_viewer.load_image(final_path)
                    
            if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
                self.fullscreen_viewer.showFullScreen()
                self.fullscreen_viewer.activateWindow()
                self.fullscreen_viewer.setFocus()

    def on_adjust_board_image_changed(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            return
        self.current_image_path = file_path
        self.current_item_kind = "image"
        self.select_image_by_path(file_path, update_preview=False)

    def on_adjust_board_image_saved(self, file_path):
        if not file_path or not os.path.isfile(file_path):
            return
        item = self.thumbnail_view.item_for_path(file_path)
        if item is not None:
            self.update_saved_thumbnail_item(file_path)
            return
        current_folder = (
            os.path.abspath(self.current_folder_path)
            if self.current_folder_path else ""
        )
        if os.path.abspath(os.path.dirname(file_path)) == current_folder:
            self.add_thumbnail_paths(
                [file_path], keep_selection_path=self.current_image_path
            )

    def rotate_image_90(self):
        self.dispatch_geometric_transform("right")

    def rotate_image_90_left(self):
        self.dispatch_geometric_transform("left")

    def flip_image_horizontal(self):
        self.dispatch_geometric_transform("flip_h")

    def flip_image_vertical(self):
        self.dispatch_geometric_transform("flip_v")

    def dispatch_geometric_transform(self, operation):
        selected_paths = self.selected_image_paths()
        if len(selected_paths) > 1:
            self.open_batch_rotate_dialog(selected_paths, operation)
            return

        from PyQt6.QtGui import QTransform
        transforms = {
            "right": QTransform().rotate(90),
            "left": QTransform().rotate(-90),
            "180": QTransform().rotate(180),
            "flip_h": QTransform().scale(-1, 1),
            "flip_v": QTransform().scale(1, -1),
        }
        transform = transforms.get(operation)
        if transform is not None:
            self.apply_geometric_transform(lambda pixmap: pixmap.transformed(transform))

    def open_batch_rotate_dialog(self, paths, initial_operation):
        if self.image_modified and not self.prompt_save_changes():
            return

        dialog = BatchRotateDialog(paths, initial_operation, self)
        if not dialog.exec() or not dialog.successful_paths:
            return

        successful = dialog.successful_paths
        selected_paths = list(paths)
        current_path = self.current_image_path
        self.clear_viewer_prefetch()
        for file_path in successful:
            self.update_saved_thumbnail_item(file_path, request_refresh=False)

        if self.sort_key == "date":
            self.reposition_thumbnail_items(successful)
            self.thumbnail_view.apply_filter()
            self.thumbnail_view.sync_worker_records()

        self.restore_thumbnail_selection(selected_paths, current_path=current_path)
        for file_path in successful:
            self.thumbnail_view.request_thumbnail_refresh(file_path)

        if current_path in successful:
            self.image_modified = False
            self.modified_pixmap = None
            self.load_prefetched_preview(current_path)
            if hasattr(self, "fullscreen_viewer") and self.fullscreen_viewer.isVisible():
                self.fullscreen_viewer.load_image(current_path)
        self.refocus_fullscreen_if_visible()

    def apply_geometric_transform(self, transform_func):
        if not self.current_image_path or self.current_item_kind != "image":
            return
            
        if not self.modified_pixmap:
            from PyQt6.QtGui import QImageReader
            reader = QImageReader(self.current_image_path)
            reader.setAutoTransform(False)
            self.modified_pixmap = QPixmap.fromImage(reader.read())
            
        self.modified_pixmap = transform_func(self.modified_pixmap)
        self.image_modified = True
        
        self.preview_viewer.set_pixmap(self.modified_pixmap)
        if hasattr(self, 'fullscreen_viewer') and self.fullscreen_viewer.isVisible():
            self.fullscreen_viewer.set_display_pixmap(self.modified_pixmap)

    def rename_file(self, parent_override=None):
        selected_images = self.selected_image_paths()
        if len(selected_images) > 1:
            self.open_batch_rename_dialog(selected_images, parent_override or self)
            return

        if self.current_image_path:
            folder, old_name = os.path.split(self.current_image_path)
            dialog = RenameDialog(old_name, parent_override or self)
            if dialog.exec() and dialog.new_filename != old_name:
                new_name = dialog.new_filename
                new_path = os.path.join(folder, new_name)
                try:
                    old_path = self.current_image_path
                    old_row = self.row_for_path(old_path)
                    os.rename(old_path, new_path)
                    self.update_renamed_thumbnail_item(old_row, old_path, new_path)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to rename: {e}")
            self.refocus_fullscreen_if_visible()

    def open_batch_rename_dialog(self, paths, parent):
        self.clear_viewer_prefetch()
        self.thumbnail_view.set_background_activity_paused(True)
        try:
            dialog = BatchRenameDialog(paths, parent)
            accepted = dialog.exec()
        finally:
            self.thumbnail_view.set_background_activity_paused(False)
        if not accepted or not dialog.rename_mapping:
            self.refocus_fullscreen_if_visible()
            return
        self.apply_batch_rename_mapping(dialog.rename_mapping, paths)
        self.refocus_fullscreen_if_visible()

    def apply_batch_rename_mapping(self, mapping, selected_old_paths):
        changed_mapping = {old: new for old, new in mapping.items() if old != new}
        if not changed_mapping:
            return

        current_old_path = self.current_image_path
        items = {}
        for old_path in changed_mapping:
            item = self.thumbnail_view.item_for_path(old_path)
            if item is not None:
                items[old_path] = item

        model = self.thumbnail_view.model()
        self.thumbnail_view.selectionModel().blockSignals(True)
        self.thumbnail_view.setUpdatesEnabled(False)
        try:
            for row in sorted((item.row() for item in items.values()), reverse=True):
                model.takeRow(row)

            for old_path, item in items.items():
                new_path = changed_mapping[old_path]
                new_name = os.path.basename(new_path)
                extension = os.path.splitext(new_name)[1][1:].lower()
                item.setData(new_path, PATH_ROLE)
                item.setData(extension, EXT_ROLE)
                try:
                    stat = os.stat(new_path)
                    item.setData(stat.st_size, SIZE_ROLE)
                    item.setData(stat.st_mtime, MODIFIED_ROLE)
                except OSError:
                    pass
                width = item.data(WIDTH_ROLE)
                height = item.data(HEIGHT_ROLE)
                item.setText(thumbnail_item_label(
                    new_name,
                    extension,
                    item.data(KIND_ROLE),
                    item.data(SIZE_ROLE),
                    width,
                    height,
                ))

            self.thumbnail_view.rename_indexed_paths(changed_mapping, items)
            for item in items.values():
                model.insertRow(self.insertion_row_for_thumbnail_item(item), item)
        finally:
            self.thumbnail_view.setUpdatesEnabled(True)
            self.thumbnail_view.selectionModel().blockSignals(False)

        self.thumbnail_view.apply_filter()
        self.thumbnail_view.sync_worker_records()
        selected_new_paths = [changed_mapping.get(path, path) for path in selected_old_paths]
        current_new_path = changed_mapping.get(current_old_path, current_old_path)
        self.current_image_path = current_new_path
        if self.fullscreen_start_path in changed_mapping:
            self.fullscreen_start_path = changed_mapping[self.fullscreen_start_path]
        if self.fullscreen_viewer.current_image_path in changed_mapping:
            self.fullscreen_viewer.set_current_image_path(
                changed_mapping[self.fullscreen_viewer.current_image_path]
            )
        self.restore_thumbnail_selection(selected_new_paths, current_path=current_new_path)

    def update_renamed_thumbnail_item(self, row, old_path, new_path):
        model = self.thumbnail_view.model()
        item = model.item(row) if row is not None else None
        if item is None or item.data(PATH_ROLE) != old_path:
            self.load_current_folder(keep_selection_path=new_path)
            return

        _, new_name = os.path.split(new_path)
        _, ext = os.path.splitext(new_name)
        ext = ext[1:].lower()
        kind = item.data(KIND_ROLE)

        try:
            stat = os.stat(new_path)
            item.setData(stat.st_size, SIZE_ROLE)
            item.setData(stat.st_mtime, MODIFIED_ROLE)
        except OSError:
            pass

        item.setData(new_path, PATH_ROLE)
        self.thumbnail_view.rename_indexed_path(old_path, new_path, item)
        item.setData(ext, EXT_ROLE)
        item.setText(thumbnail_item_label(
            new_name,
            ext,
            kind,
            item.data(SIZE_ROLE),
            item.data(WIDTH_ROLE),
            item.data(HEIGHT_ROLE),
        ))

        self.current_image_path = new_path
        self.current_item_kind = kind
        if self.fullscreen_start_path == old_path:
            self.fullscreen_start_path = new_path
        if self.fullscreen_viewer.current_image_path == old_path:
            self.fullscreen_viewer.set_current_image_path(new_path)
        self.thumbnail_view.sync_worker_records()
        if kind == "video":
            self.thumbnail_view.request_video_thumbnails([new_path])
        self.select_image_by_path(new_path)
        self.thumbnail_view.apply_filter()
        self.update_status_bar()
                    
    def copy_to_clipboard(self):
        self.set_file_clipboard(cut=False)

    def cut_to_clipboard(self):
        self.set_file_clipboard(cut=True)

    def set_file_clipboard(self, cut=False):
        paths = self.selected_clipboard_paths()
        if not paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in paths])
        mime_data.setData("application/x-a5imageviewer-cut", b"1" if cut else b"0")
        drop_effect = 2 if cut else 1
        mime_data.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', drop_effect.to_bytes(4, "little"))
        QApplication.clipboard().setMimeData(mime_data)

    def paste_from_clipboard(self):
        if not self.current_folder_path or not os.path.isdir(self.current_folder_path):
            return
        mime_data = QApplication.clipboard().mimeData()
        paths = self.paths_from_mime_data(mime_data)
        if not paths:
            return

        move_files = self.mime_data_requests_move(mime_data)
        self.transfer_files_to_folder(paths, self.current_folder_path, move_files=move_files)

    def paths_from_mime_data(self, mime_data):
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile()
            if path:
                paths.append(path)
        return paths

    def mime_data_requests_move(self, mime_data):
        marker = bytes(mime_data.data("application/x-a5imageviewer-cut"))
        if marker == b"1":
            return True

        data = bytes(mime_data.data('application/x-qt-windows-mime;value="Preferred DropEffect"'))
        if len(data) >= 4:
            effect = int.from_bytes(data[:4], "little")
            return effect == 2
        return False

    def show_thumbnail_context_menu(self, pos):
        index = self.thumbnail_view.indexAt(pos)
        if index.isValid():
            selection = self.thumbnail_view.selectionModel()
            if not selection.isSelected(index):
                self.thumbnail_view.setCurrentIndex(index)
            self.current_image_path = index.data(PATH_ROLE)
            self.current_item_kind = index.data(KIND_ROLE)

        if not self.current_image_path:
            return
            
        menu = QMenu(self)
        

        if self.current_item_kind == "folder":
            folder_path = self.current_image_path
            open_action = QAction("Open in File Explorer", self)
            open_action.triggered.connect(
                lambda: self.open_folder_in_file_explorer(folder_path)
            )
            menu.addAction(open_action)

            favorite_action = QAction("Add to Favorites", self)
            favorite_action.triggered.connect(
                lambda: self.add_folder_to_favorites(folder_path)
            )
            menu.addAction(favorite_action)
            menu.addSeparator()

        convert_action = QAction("Batch Convert...", self)
        convert_action.triggered.connect(self.open_convert_dialog)
        menu.addAction(convert_action)
        menu.addSeparator()

        new_folder_action = QAction("Create New Folder...", self)
        new_folder_action.triggered.connect(self.create_folder_in_current_folder)
        menu.addAction(new_folder_action)
        menu.addSeparator()

        copy_action = QAction("Copy To... (C)", self)
        copy_action.triggered.connect(self.open_copy_dialog)
        menu.addAction(copy_action)
        
        move_action = QAction("Move To... (M)", self)
        move_action.triggered.connect(self.open_move_dialog)
        menu.addAction(move_action)

        if self.current_item_kind != "folder":
            self.add_open_with_menu(menu, self.current_image_path)
            self.add_send_to_menu(menu, self.selected_file_paths())
            if self.current_item_kind == "image":
                self.add_windows_image_actions(menu, self.current_image_path)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self.delete_selected_files())
        menu.addAction(delete_action)
        
        editable_image = (
            self.current_item_kind == "image" and
            self.is_editable_image_path(self.current_image_path)
        )

        crop_action = QAction("Crop (X)", self)
        crop_action.setEnabled(editable_image)
        crop_action.triggered.connect(self.open_crop_board)
        menu.addAction(crop_action)
        
        adjust_action = QAction("Adjust Colors & Size (A)", self)
        adjust_action.setEnabled(editable_image)
        adjust_action.triggered.connect(self.open_adjust_board)
        menu.addAction(adjust_action)
        
        menu.addSeparator()
        
        rotate_left_action = QAction("Rotate 90 degrees left\tL", self)
        rotate_left_action.setEnabled(self.current_item_kind == "image")
        rotate_left_action.triggered.connect(self.rotate_image_90_left)
        menu.addAction(rotate_left_action)

        rotate_action = QAction("Rotate 90 degrees right\tR", self)
        rotate_action.setEnabled(self.current_item_kind == "image")
        rotate_action.triggered.connect(self.rotate_image_90)
        menu.addAction(rotate_action)
        
        flip_h_action = QAction("Flip Horizontal\tH", self)
        flip_h_action.setEnabled(self.current_item_kind == "image")
        flip_h_action.triggered.connect(self.flip_image_horizontal)
        menu.addAction(flip_h_action)
        
        flip_v_action = QAction("Flip Vertical\tV", self)
        flip_v_action.setEnabled(self.current_item_kind == "image")
        flip_v_action.triggered.connect(self.flip_image_vertical)
        menu.addAction(flip_v_action)
        
        menu.addSeparator()
        
        rename_action = QAction("Rename (F2)", self)
        rename_action.triggered.connect(self.rename_file)
        menu.addAction(rename_action)
        
        copy_clip_action = QAction("Copy (Ctrl+C)", self)
        copy_clip_action.triggered.connect(self.copy_to_clipboard)
        menu.addAction(copy_clip_action)

        cut_clip_action = QAction("Cut (Ctrl+X)", self)
        cut_clip_action.triggered.connect(self.cut_to_clipboard)
        menu.addAction(cut_clip_action)

        paste_clip_action = QAction("Paste (Ctrl+V)", self)
        paste_clip_action.triggered.connect(self.paste_from_clipboard)
        menu.addAction(paste_clip_action)
        
        menu.addSeparator()
        
        refresh_action = QAction("Refresh (F5)", self)
        refresh_action.triggered.connect(self.refresh_folder)
        menu.addAction(refresh_action)

        # Map to global relative to thumbnail_view
        menu.exec(self.thumbnail_view.viewport().mapToGlobal(pos))

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.thumbnail_size_changed.connect(self.thumbnail_view.set_thumbnail_size)
        dialog.resource_settings_changed.connect(self.apply_resource_settings)
        dialog.theme_changed.connect(apply_theme)
        dialog.exec()

    def apply_resource_settings(self, settings):
        self.clear_viewer_prefetch()
        self.resource_settings = settings
        self.thumbnail_view.apply_resource_settings(settings)
        self.crop_prefetch_service.configure(settings)

    def open_convert_dialog(self):
        indexes = self.thumbnail_view.selectionModel().selectedIndexes()
        files = []
        for index in indexes:
            if index.data(KIND_ROLE) == "image":
                files.append(index.data(PATH_ROLE))
                
        if not files:
            QMessageBox.information(self, "Convert", "Please select at least one image to convert.")
            return
            
        dialog = ConvertDialog(files, self)
        if dialog.exec():
            self.refresh_folder()
