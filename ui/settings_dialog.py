import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QSlider, QGroupBox, QFormLayout, QSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal
from utils.file_ops import (RESOURCE_PROFILES, get_thumbnail_size, set_thumbnail_size,
                            get_startup_behavior, set_startup_behavior,
                            get_resource_settings, set_resource_settings,
                            get_ui_theme, set_ui_theme)
from ui.theme import THEME_NAMES

class SettingsDialog(QDialog):
    thumbnail_size_changed = pyqtSignal(int)
    resource_settings_changed = pyqtSignal(object)
    theme_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(430, 430)
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
        layout.addWidget(general_group)
        
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
        layout.addWidget(resource_group)

        self.resource_combo.currentIndexChanged.connect(self.on_resource_profile_changed)
        self.worker_spin.valueChanged.connect(self.remember_custom_values)
        self.cache_spin.valueChanged.connect(self.remember_custom_values)
        self.prefetch_spin.valueChanged.connect(self.remember_custom_values)
        self.on_resource_profile_changed()
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
    def on_slider_changed(self, value):
        self.val_label.setText(f"{value} px")

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
        old_resources = get_resource_settings()
        old_theme = get_ui_theme()
        new_theme = self.theme_combo.currentData()
        old_size = get_thumbnail_size()
        new_size = self.thumb_slider.value()
        set_thumbnail_size(new_size)
        set_startup_behavior(self.startup_combo.currentData())
        set_ui_theme(new_theme)
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
        if new_theme != old_theme:
            self.theme_changed.emit(new_theme)
        super().accept()
