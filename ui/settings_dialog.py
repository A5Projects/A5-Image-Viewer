import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QSlider, QGroupBox, QFormLayout, QSpinBox, QCheckBox,
                             QFileDialog, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from utils.file_ops import (RESOURCE_PROFILES, get_thumbnail_size, set_thumbnail_size,
                            MAX_FOLDER_HISTORY_LIMIT, get_folder_history_limits, set_folder_history_limits,
                            get_gif_playback_settings, set_gif_playback_settings,
                            get_startup_behavior, set_startup_behavior,
                            get_resource_settings, set_resource_settings,
                            get_ui_theme, set_ui_theme,
                            get_viewer_default_mode, set_viewer_default_mode,
                            get_image_settings, set_image_settings,
                            MIN_DISK_CACHE_MB, MAX_DISK_CACHE_MB,
                            get_disk_cache_settings, set_disk_cache_settings,
                            resolve_disk_cache_dir, normalize_folder_path)
from utils.image_loading import apply_image_loading_settings
from ui.theme import THEME_NAMES
from ui.thumbnail_disk_cache import ThumbnailDiskCache
from ui.thumbnail_view import format_thumbnail_file_size
from ui.about_dialog import install_about_shortcut, show_about

class SettingsDialog(QDialog):
    thumbnail_size_changed = pyqtSignal(int)
    gif_playback_changed = pyqtSignal(bool, bool)
    visited_folder_limit_changed = pyqtSignal()
    resource_settings_changed = pyqtSignal(object)
    disk_cache_settings_changed = pyqtSignal(object)
    clear_disk_cache_requested = pyqtSignal()
    theme_changed = pyqtSignal(str)
    image_settings_changed = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        install_about_shortcut(self, "Settings and dialogs")
        self.setWindowTitle("Settings")
        self.resize(580, 670)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        
        layout = QVBoxLayout(self)
        
        # General Settings
        general_group = QGroupBox("General")
        form_layout = QFormLayout(general_group)
        
        self.startup_combo = QComboBox()
        self.startup_combo.addItem("Last Used Folder", "last_used")
        self.startup_combo.addItem("Empty View", "empty")
        
        current_startup = get_startup_behavior()
        idx = self.startup_combo.findData(current_startup)
        if idx >= 0:
            self.startup_combo.setCurrentIndex(idx)
            
        form_layout.addRow("Startup Behavior:", self.startup_combo)
        self.theme_combo = QComboBox()
        for name, label in THEME_NAMES:
            self.theme_combo.addItem(label, name)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(get_ui_theme()))
        form_layout.addRow("Theme:", self.theme_combo)
        self.viewer_mode_combo = QComboBox()
        self.viewer_mode_combo.addItem("Fullscreen", "fullscreen")
        self.viewer_mode_combo.addItem("Windowed", "windowed")
        self.viewer_mode_combo.addItem("Remember last used", "last_used")
        self.viewer_mode_combo.setCurrentIndex(self.viewer_mode_combo.findData(get_viewer_default_mode()))
        form_layout.addRow("Default image view:", self.viewer_mode_combo)
        image_settings = get_image_settings()
        self.smooth_check = QCheckBox("Smooth downscaling")
        self.smooth_check.setChecked(image_settings["smooth_downscaling"])
        self.smooth_check.setToolTip(
            "Smooth images below 100% zoom in the preview and image viewer. "
            "Uses the CPU; 100% and larger remain unsmoothed."
        )
        form_layout.addRow(self.smooth_check)
        layout.addWidget(general_group)

        history_group = QGroupBox("Folder history")
        history_layout = QFormLayout(history_group)
        visited, destinations = get_folder_history_limits()
        self.visited_limit_spin = QSpinBox()
        self.visited_limit_spin.setRange(1, MAX_FOLDER_HISTORY_LIMIT)
        self.visited_limit_spin.setValue(visited)
        self.destination_limit_spin = QSpinBox()
        self.destination_limit_spin.setRange(1, MAX_FOLDER_HISTORY_LIMIT)
        self.destination_limit_spin.setValue(destinations)
        history_layout.addRow("Visited folders:", self.visited_limit_spin)
        history_layout.addRow("Copy To / Move To destinations:", self.destination_limit_spin)
        layout.addWidget(history_group)
        
        # Thumbnail Settings
        thumb_group = QGroupBox("Thumbnails")
        thumb_layout = QVBoxLayout(thumb_group)
        
        slider_layout = QHBoxLayout()
        self.thumb_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumb_slider.setRange(100, 256)
        self.thumb_slider.setSingleStep(10)
        
        current_size = get_thumbnail_size()
        self.thumb_slider.setValue(current_size)
        
        self.val_label = QLabel(f"{current_size} px")
        self.val_label.setMinimumWidth(50)
        self.val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.thumb_slider.valueChanged.connect(self.on_slider_changed)
        
        slider_layout.addWidget(QLabel("Size:"))
        slider_layout.addWidget(self.thumb_slider)
        slider_layout.addWidget(self.val_label)
        
        thumb_layout.addLayout(slider_layout)
        animate_gifs, only_in_preview = get_gif_playback_settings()
        self.animate_gifs_check = QCheckBox("Animate GIFs")
        self.animate_gifs_check.setToolTip("Play animated GIFs in visible thumbnails and the selected image preview.")
        self.animate_gifs_check.setChecked(animate_gifs)
        self.gif_preview_only_check = QCheckBox("Only in preview")
        self.gif_preview_only_check.setToolTip("Play the selected GIF in the preview pane and keep thumbnails still.")
        self.gif_preview_only_check.setChecked(only_in_preview)
        self.gif_preview_only_check.setEnabled(animate_gifs)
        self.animate_gifs_check.toggled.connect(self.gif_preview_only_check.setEnabled)
        gif_layout = QHBoxLayout()
        gif_layout.addWidget(self.animate_gifs_check)
        gif_layout.addWidget(self.gif_preview_only_check)
        gif_layout.addStretch()
        thumb_layout.addLayout(gif_layout)

        disk_settings = get_disk_cache_settings()
        self._initial_disk_cache_settings = disk_settings

        disk_row = QHBoxLayout()
        self.disk_cache_check = QCheckBox("Save thumbnails to disk")
        self.disk_cache_check.setToolTip(
            "Keep scaled thumbnails in a local SQLite database so revisited folders "
            "and thumbnail size changes do not re-read full images."
        )
        self.disk_cache_check.setChecked(disk_settings["enabled"])
        disk_row.addWidget(self.disk_cache_check)
        disk_row.addStretch()
        disk_row.addWidget(QLabel("Limit:"))
        self.disk_cache_limit_spin = QSpinBox()
        self.disk_cache_limit_spin.setRange(MIN_DISK_CACHE_MB, MAX_DISK_CACHE_MB)
        self.disk_cache_limit_spin.setSingleStep(128)
        self.disk_cache_limit_spin.setSuffix(" MiB")
        self.disk_cache_limit_spin.setValue(disk_settings["max_mb"])
        disk_row.addWidget(self.disk_cache_limit_spin)
        thumb_layout.addLayout(disk_row)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder:"))
        self.disk_cache_dir_edit = QLineEdit()
        self.disk_cache_dir_edit.setText(disk_settings["custom_dir"])
        default_dir = resolve_disk_cache_dir("")
        self.disk_cache_dir_edit.setPlaceholderText(default_dir)
        self.disk_cache_dir_edit.setToolTip(
            f"Leave empty for the default local cache folder:\n{default_dir}"
        )
        self.disk_cache_dir_edit.textChanged.connect(self.update_disk_cache_usage)
        folder_row.addWidget(self.disk_cache_dir_edit, 1)
        self.disk_cache_browse_btn = QPushButton("Browse…")
        self.disk_cache_browse_btn.setAutoDefault(False)
        self.disk_cache_browse_btn.clicked.connect(self.browse_disk_cache_dir)
        folder_row.addWidget(self.disk_cache_browse_btn)
        self.disk_cache_default_btn = QPushButton("Default")
        self.disk_cache_default_btn.setAutoDefault(False)
        self.disk_cache_default_btn.clicked.connect(self.reset_disk_cache_dir)
        folder_row.addWidget(self.disk_cache_default_btn)
        thumb_layout.addLayout(folder_row)

        usage_row = QHBoxLayout()
        self.disk_cache_usage_label = QLabel()
        usage_row.addWidget(self.disk_cache_usage_label)
        usage_row.addStretch()
        self.disk_cache_clear_btn = QPushButton("Clear cache")
        self.disk_cache_clear_btn.setAutoDefault(False)
        self.disk_cache_clear_btn.clicked.connect(self.clear_disk_cache)
        usage_row.addWidget(self.disk_cache_clear_btn)
        thumb_layout.addLayout(usage_row)

        self.disk_cache_check.toggled.connect(self._update_disk_cache_controls)
        self._update_disk_cache_controls(disk_settings["enabled"])
        self.update_disk_cache_usage()
        layout.addWidget(thumb_group)

        resource_group = QGroupBox("Resource Usage")
        resource_layout = QFormLayout(resource_group)
        self.resource_combo = QComboBox()
        self.resource_combo.addItem("Conservative", "conservative")
        self.resource_combo.addItem("Balanced", "balanced")
        self.resource_combo.addItem("Performance", "performance")
        self.resource_combo.addItem("Custom", "custom")

        current_resources = get_resource_settings()
        self.custom_resource_values = {
            "workers": current_resources["custom_thumbnail_workers"],
            "cache": current_resources["custom_thumbnail_cache_mb"],
            "prefetch": current_resources["custom_crop_prefetch_mb"],
        }
        resource_index = self.resource_combo.findData(current_resources["profile"])
        self.resource_combo.setCurrentIndex(max(0, resource_index))

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 8)
        self.worker_spin.setValue(current_resources["requested_thumbnail_workers"])
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(256, 5120)
        self.cache_spin.setSingleStep(256)
        self.cache_spin.setSuffix(" MiB")
        self.cache_spin.setValue(current_resources["thumbnail_cache_mb"])
        self.prefetch_spin = QSpinBox()
        self.prefetch_spin.setRange(128, 1024)
        self.prefetch_spin.setSingleStep(128)
        self.prefetch_spin.setSuffix(" MiB")
        self.prefetch_spin.setValue(current_resources["crop_prefetch_mb"])

        resource_layout.addRow("Profile:", self.resource_combo)
        resource_layout.addRow("Thumbnail workers:", self.worker_spin)
        resource_layout.addRow("Thumbnail cache:", self.cache_spin)
        resource_layout.addRow("Crop prefetch:", self.prefetch_spin)
        self.image_limit_spin = QSpinBox()
        self.image_limit_spin.setRange(64, 65536)
        self.image_limit_spin.setSingleStep(256)
        self.image_limit_spin.setSuffix(" MiB")
        self.image_limit_spin.setValue(image_settings["max_decoded_image_mb"])
        self.image_limit_spin.setToolTip(
            "Limit for a single decoded image, independent of the cache profile. "
            "Total application memory can be higher due to editing and display copies."
        )
        resource_layout.addRow("Maximum decoded image size:", self.image_limit_spin)
        prefetch_note = QLabel("Images above 256 MiB are loaded on demand and are not preloaded.")
        prefetch_note.setWordWrap(True)
        resource_layout.addRow(prefetch_note)
        layout.addWidget(resource_group)

        self.resource_combo.currentIndexChanged.connect(self.on_resource_profile_changed)
        self.worker_spin.valueChanged.connect(self.remember_custom_values)
        self.cache_spin.valueChanged.connect(self.remember_custom_values)
        self.prefetch_spin.valueChanged.connect(self.remember_custom_values)
        self.on_resource_profile_changed()
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.about_button = QPushButton("About…")
        self.about_button.clicked.connect(lambda: show_about(self, "Settings and dialogs"))
        btn_layout.addWidget(self.about_button)
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
    def on_slider_changed(self, value):
        self.val_label.setText(f"{value} px")

    def _effective_disk_cache_dir(self):
        return resolve_disk_cache_dir(self.disk_cache_dir_edit.text())

    def _update_disk_cache_controls(self, enabled):
        enabled = bool(enabled)
        self.disk_cache_limit_spin.setEnabled(enabled)
        self.disk_cache_dir_edit.setEnabled(enabled)
        self.disk_cache_browse_btn.setEnabled(enabled)
        self.disk_cache_default_btn.setEnabled(enabled)

    def update_disk_cache_usage(self):
        used = ThumbnailDiskCache.directory_usage_bytes(self._effective_disk_cache_dir())
        self.disk_cache_usage_label.setText(f"Used: {format_thumbnail_file_size(used)}")

    def browse_disk_cache_dir(self):
        start_dir = self._effective_disk_cache_dir()
        if not os.path.isdir(start_dir):
            parent_dir = os.path.dirname(start_dir)
            start_dir = parent_dir if os.path.isdir(parent_dir) else ""
        chosen = QFileDialog.getExistingDirectory(self, "Select Thumbnail Cache Folder", start_dir)
        if chosen:
            self.disk_cache_dir_edit.setText(normalize_folder_path(chosen))

    def reset_disk_cache_dir(self):
        self.disk_cache_dir_edit.clear()
        self.update_disk_cache_usage()

    def clear_disk_cache(self):
        target_dir = self._effective_disk_cache_dir()
        connected = self.receivers(self.clear_disk_cache_requested) > 0
        if connected:
            self.clear_disk_cache_requested.emit()
        active_dir = (
            self._initial_disk_cache_settings.get("effective_dir", "")
            if self._initial_disk_cache_settings.get("enabled")
            else ""
        )
        if not connected or not active_dir or os.path.normcase(target_dir) != os.path.normcase(active_dir):
            ThumbnailDiskCache.clear_directory(target_dir)
        self.update_disk_cache_usage()

    def on_resource_profile_changed(self):
        profile = self.resource_combo.currentData()
        custom = profile == "custom"
        if custom:
            self.worker_spin.blockSignals(True)
            self.cache_spin.blockSignals(True)
            self.prefetch_spin.blockSignals(True)
            self.worker_spin.setValue(self.custom_resource_values["workers"])
            self.cache_spin.setValue(self.custom_resource_values["cache"])
            self.prefetch_spin.setValue(self.custom_resource_values["prefetch"])
            self.worker_spin.blockSignals(False)
            self.cache_spin.blockSignals(False)
            self.prefetch_spin.blockSignals(False)
        elif profile in RESOURCE_PROFILES:
            preset = RESOURCE_PROFILES[profile]
            self.worker_spin.setValue(preset["thumbnail_workers"])
            self.cache_spin.setValue(preset["thumbnail_cache_mb"])
            self.prefetch_spin.setValue(preset["crop_prefetch_mb"])
        self.worker_spin.setEnabled(custom)
        self.cache_spin.setEnabled(custom)
        self.prefetch_spin.setEnabled(custom)

    def remember_custom_values(self):
        if self.resource_combo.currentData() != "custom":
            return
        self.custom_resource_values = {
            "workers": self.worker_spin.value(),
            "cache": self.cache_spin.value(),
            "prefetch": self.prefetch_spin.value(),
        }
        
    def accept(self):
        old_image_settings = get_image_settings()
        old_resources = get_resource_settings()
        old_disk_cache = get_disk_cache_settings()
        old_theme = get_ui_theme()
        new_theme = self.theme_combo.currentData()
        old_size = get_thumbnail_size()
        new_size = self.thumb_slider.value()
        old_limits = get_folder_history_limits()
        limits = self.visited_limit_spin.value(), self.destination_limit_spin.value()
        if limits != old_limits:
            set_folder_history_limits(*limits)
            if limits[0] != old_limits[0]:
                self.visited_folder_limit_changed.emit()
        gif_settings = self.animate_gifs_check.isChecked(), self.gif_preview_only_check.isChecked()
        if gif_settings != get_gif_playback_settings():
            set_gif_playback_settings(*gif_settings)
            self.gif_playback_changed.emit(*gif_settings)
        set_thumbnail_size(new_size)
        set_startup_behavior(self.startup_combo.currentData())
        set_ui_theme(new_theme)
        set_viewer_default_mode(self.viewer_mode_combo.currentData())
        set_image_settings(self.image_limit_spin.value(), self.smooth_check.isChecked())
        apply_image_loading_settings()
        new_image_settings = get_image_settings()
        if new_image_settings != old_image_settings:
            self.image_settings_changed.emit(new_image_settings)
        set_disk_cache_settings(
            self.disk_cache_check.isChecked(),
            self.disk_cache_limit_spin.value(),
            self.disk_cache_dir_edit.text(),
        )
        new_disk_cache = get_disk_cache_settings()
        if self.resource_combo.currentData() == "custom":
            custom_workers = self.worker_spin.value()
            custom_cache = self.cache_spin.value()
            custom_prefetch = self.prefetch_spin.value()
        else:
            custom_workers = self.custom_resource_values["workers"]
            custom_cache = self.custom_resource_values["cache"]
            custom_prefetch = self.custom_resource_values["prefetch"]
        set_resource_settings(
            self.resource_combo.currentData(),
            custom_workers,
            custom_cache,
            custom_prefetch
        )
        if new_size != old_size:
            self.thumbnail_size_changed.emit(new_size)
        new_resources = get_resource_settings()
        if new_resources != old_resources:
            self.resource_settings_changed.emit(new_resources)
        if new_disk_cache != old_disk_cache:
            self.disk_cache_settings_changed.emit(new_disk_cache)
        if new_theme != old_theme:
            self.theme_changed.emit(new_theme)
        super().accept()
