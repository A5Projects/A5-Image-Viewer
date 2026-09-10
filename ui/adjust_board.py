import math
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene, 
                             QGraphicsPixmapItem, QSlider, QLabel, QPushButton, QCheckBox, 
                             QSpinBox, QDoubleSpinBox, QComboBox, QGroupBox, QGridLayout,
                             QWidget, QMessageBox, QSizePolicy, QToolButton, QFileDialog,
                             QColorDialog)
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QShortcut, QKeySequence, QColor
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from utils.file_ops import (get_adjustment_settings, set_adjustment_settings,
                            get_adjust_auto_name_copies, set_adjust_auto_name_copies,
                            get_adjust_resampling, set_adjust_resampling)

class AdjustBoard(QDialog):
    image_saved = pyqtSignal(str)
    image_changed = pyqtSignal(str)
    _session_navigation_choice = None

    CONTROL_COLUMNS = (
        (
            ("Brightness", -100, 100, 0, 1, 0),
            ("Contrast", -100, 100, 0, 1, 0),
            ("Gamma", 10, 300, 100, 100, 2),
            ("Exposure", -300, 300, 0, 100, 2),
            ("Sharpness", -100, 100, 0, 1, 0),
        ),
        (
            ("Temperature", -100, 100, 0, 1, 0),
            ("Tint", -100, 100, 0, 1, 0),
            ("Hue", -180, 180, 0, 1, 0),
            ("Saturation", -100, 100, 0, 1, 0),
        ),
        (
            ("Red", -100, 100, 0, 1, 0),
            ("Green", -100, 100, 0, 1, 0),
            ("Blue", -100, 100, 0, 1, 0),
            ("Shadows", -100, 100, 0, 1, 0),
            ("Highlights", -100, 100, 0, 1, 0),
        ),
    )
    TOGGLE_NAMES = ("Grayscale", "Invert", "Auto Contrast", "Equalize")
    RESAMPLING_METHODS = {
        "auto": Image.Resampling.LANCZOS,
        "lanczos": Image.Resampling.LANCZOS,
        "lanczos_sharper": Image.Resampling.LANCZOS,
        "bicubic": Image.Resampling.BICUBIC,
        "bicubic_sharper": Image.Resampling.BICUBIC,
        "bilinear": Image.Resampling.BILINEAR,
        "hamming": Image.Resampling.HAMMING,
        "nearest": Image.Resampling.NEAREST,
        "box": Image.Resampling.BOX,
    }

    def __init__(self, image_path, parent=None, navigation_paths=None):
        super().__init__(parent)
        self.image_path = image_path
        self.navigation_paths = list(navigation_paths or [])
        self.navigation_positions = {
            path: index for index, path in enumerate(self.navigation_paths)
        }
        self.saved_any = False
        self.zoom_mode = "fit"
        self.last_resize_axis = "width"
        self.remember_adjustments, self.remembered_values = get_adjustment_settings()
        self.auto_name_copies = get_adjust_auto_name_copies()
        self.remembered_resampling = get_adjust_resampling()
        self.padding_color = QColor("#000000")
        self.setWindowTitle("Adjust Colors & Size")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(1120, 680)
        self.resize(1280, 800)
        self._initial_fit_done = False

        self.original_pil = self.read_image(self.image_path)
        self.build_preview_source()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(40)
        self.preview_timer.timeout.connect(self.apply_preview_adjustments)
        
        self.init_ui()
        self.saved_signature = self.neutral_edit_signature()
        self.update_preview()
        self.fit_preview()
        self.update_navigation_buttons()

    @staticmethod
    def read_image(image_path):
        with Image.open(image_path) as img:
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                return img.convert("RGBA")
            return img.convert("RGB")

    def build_preview_source(self):
        self.preview_original_pil = self.original_pil.copy()
        self.preview_original_pil.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        self.preview_current_pil = self.preview_original_pil.copy()

    def add_preview_tool_button(self, layout, text, tooltip, callback):
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFixedSize(34, 34)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @classmethod
    def adjustment_defaults(cls):
        return {
            spec[0]: spec[3]
            for column in cls.CONTROL_COLUMNS
            for spec in column
        }

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Preview Area
        self.view = QGraphicsView()
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # remove scrollbars
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.viewport().installEventFilter(self)

        preview_layout = QHBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(self.view, stretch=1)

        preview_tools = QVBoxLayout()
        preview_tools.setSpacing(4)
        self.btn_previous = self.add_preview_tool_button(
            preview_tools, "<", "Previous image (P / PgUp)",
            lambda: self.open_adjacent_image(-1)
        )
        self.btn_next = self.add_preview_tool_button(
            preview_tools, ">", "Next image (N / PgDown)",
            lambda: self.open_adjacent_image(1)
        )
        preview_tools.addSpacing(8)
        self.add_preview_tool_button(preview_tools, "+", "Zoom in (+)", self.zoom_in)
        self.add_preview_tool_button(preview_tools, "-", "Zoom out (-)", self.zoom_out)
        self.add_preview_tool_button(preview_tools, "*", "Fit to window (*)", self.fit_preview)
        self.add_preview_tool_button(preview_tools, "1:1", "Actual preview size (/)", self.actual_size)
        preview_tools.addStretch(1)
        preview_layout.addLayout(preview_tools)

        main_layout.addLayout(preview_layout, stretch=1)
        
        # Bottom Panel
        bottom_panel = QWidget()
        bottom_layout = QHBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 10, 0, 0)
        bottom_layout.setSpacing(8)
        
        # Left: Adjustments Grid
        adj_group = QGroupBox("Adjustments")
        adj_outer_layout = QVBoxLayout(adj_group)
        adj_outer_layout.setContentsMargins(8, 6, 8, 6)
        adj_outer_layout.setSpacing(4)
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(12)

        self.sliders = {}
        self.value_inputs = {}
        self.control_scales = {}
        for column_specs in self.CONTROL_COLUMNS:
            column_widget = QWidget()
            column_layout = QGridLayout(column_widget)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setHorizontalSpacing(5)
            column_layout.setVerticalSpacing(2)
            column_widget.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Preferred,
            )
            for row, spec in enumerate(column_specs):
                self.add_adjustment_control(column_layout, row, *spec)
            columns_layout.addWidget(column_widget)
        adj_outer_layout.addLayout(columns_layout)

        toggle_layout = QHBoxLayout()
        toggle_layout.setContentsMargins(0, 2, 0, 0)
        toggle_layout.setSpacing(12)
        self.effect_checks = {}
        for name in self.TOGGLE_NAMES:
            checkbox = QCheckBox(name)
            checkbox.setChecked(
                bool(self.remembered_values.get(name, False))
                if self.remember_adjustments else False
            )
            checkbox.toggled.connect(self.on_adjustment_changed)
            self.effect_checks[name] = checkbox
            toggle_layout.addWidget(checkbox)

        self.padding_color_label = QLabel("Pad")
        self.padding_color_button = QToolButton(self)
        self.padding_color_button.setFixedSize(28, 22)
        self.padding_color_button.setToolTip("Choose padding color")
        self.padding_color_button.clicked.connect(self.choose_padding_color)
        toggle_layout.addWidget(self.padding_color_label)
        toggle_layout.addWidget(self.padding_color_button)
        self.update_padding_color_button()
        self.set_padding_controls_visible(False)

        self.check_remember = QCheckBox("Remember settings")
        self.check_remember.setChecked(self.remember_adjustments)
        self.check_remember.toggled.connect(self.on_remember_toggled)
        toggle_layout.addStretch(1)
        toggle_layout.addWidget(self.check_remember)
        adj_outer_layout.addLayout(toggle_layout)

            
        adj_group.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        bottom_layout.addWidget(adj_group)
        
        # Middle: Resize Grid
        resize_group = QGroupBox("Resize")
        resize_layout = QGridLayout(resize_group)
        resize_layout.setContentsMargins(8, 6, 8, 6)
        resize_layout.setHorizontalSpacing(5)
        resize_layout.setVerticalSpacing(4)
        resize_group.setMaximumWidth(240)
        resize_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        self.resize_mode_combo = QComboBox()
        self.resize_mode_combo.addItem("Pixels", "pixels")
        self.resize_mode_combo.addItem("Percent", "percent")
        self.resize_mode_combo.currentIndexChanged.connect(self.on_resize_mode_changed)
        
        self.spin_width = QSpinBox()
        self.spin_width.setRange(1, 100000)
        self.spin_width.setValue(self.original_pil.width)
        self.spin_width.setMaximumWidth(110)
        
        self.spin_height = QSpinBox()
        self.spin_height.setRange(1, 100000)
        self.spin_height.setValue(self.original_pil.height)
        self.spin_height.setMaximumWidth(110)

        self.resample_combo = QComboBox()
        for label, key in (
            ("Automatic", "auto"),
            ("Lanczos", "lanczos"),
            ("Lanczos + Sharpen", "lanczos_sharper"),
            ("Bicubic", "bicubic"),
            ("Bicubic + Sharpen", "bicubic_sharper"),
            ("Bilinear", "bilinear"),
            ("Hamming", "hamming"),
            ("Nearest", "nearest"),
            ("Box", "box"),
        ):
            self.resample_combo.addItem(label, key)
        remembered_index = self.resample_combo.findData(self.remembered_resampling)
        self.resample_combo.setCurrentIndex(max(0, remembered_index))
        self.resample_combo.currentIndexChanged.connect(self.on_resampling_changed)

        self.geometry_combo = QComboBox()
        for label, key in (
            ("Preserve ratio", "preserve"),
            ("Stretch", "stretch"),
            ("Fit inside", "fit"),
            ("Fill and crop", "fill"),
            ("Pad", "pad"),
        ):
            self.geometry_combo.addItem(label, key)
        self.geometry_combo.currentIndexChanged.connect(self.on_geometry_changed)

        # Compatibility proxy for callers that used the former checkbox.
        self.check_aspect = QCheckBox()
        self.check_aspect.setChecked(True)
        self.check_aspect.toggled.connect(self.on_aspect_changed)

        self.check_remember_resize = QCheckBox("Remember resize")
        self.check_remember_resize.setChecked(False)
        
        self.spin_width.valueChanged.connect(self.on_width_changed)
        self.spin_height.valueChanged.connect(self.on_height_changed)
        
        resize_layout.addWidget(QLabel("Mode"), 0, 0)
        resize_layout.addWidget(self.resize_mode_combo, 0, 1)
        resize_layout.addWidget(QLabel("Width"), 1, 0)
        resize_layout.addWidget(self.spin_width, 1, 1)
        resize_layout.addWidget(QLabel("Height"), 2, 0)
        resize_layout.addWidget(self.spin_height, 2, 1)
        resize_layout.addWidget(QLabel("Geometry"), 3, 0)
        resize_layout.addWidget(self.geometry_combo, 3, 1)
        resize_layout.addWidget(QLabel("Filter"), 4, 0)
        resize_layout.addWidget(self.resample_combo, 4, 1)
        resize_layout.addWidget(self.check_remember_resize, 5, 0, 1, 2)
        
        bottom_layout.addWidget(resize_group)
        
        # Right: Buttons
        btn_layout = QVBoxLayout()
        
        self.btn_original = QPushButton("Hold for Original")
        self.btn_original.pressed.connect(self.show_original)
        self.btn_original.released.connect(self.show_current)
        
        self.btn_reset = QPushButton("&Reset")
        self.btn_reset.clicked.connect(self.reset_adjustments)

        self.check_auto_name = QCheckBox("Auto-name _adj copies")
        self.check_auto_name.setChecked(self.auto_name_copies)
        self.check_auto_name.toggled.connect(self.on_auto_name_toggled)

        self.btn_save_file = QPushButton("Save to &File...")
        self.btn_save_file.clicked.connect(self.save_to_file)

        self.btn_ok = QPushButton("&OK (Save)")
        self.btn_ok.clicked.connect(self.apply_and_save)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_original)
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addWidget(self.check_auto_name)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save_file)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        
        bottom_layout.addLayout(btn_layout)
        bottom_layout.addStretch(1)
        
        main_layout.addWidget(bottom_panel)

        self._updating_spins = False
        for button in (
            self.btn_original, self.btn_reset, self.btn_save_file,
            self.btn_ok, self.btn_cancel,
        ):
            button.setAutoDefault(False)
            button.setDefault(False)

        self.shortcuts = []
        for sequence, callback in (
            (Qt.Key.Key_PageUp, lambda: self.open_adjacent_image(-1)),
            (Qt.Key.Key_PageDown, lambda: self.open_adjacent_image(1)),
            ("P", lambda: self.open_adjacent_image(-1)),
            ("N", lambda: self.open_adjacent_image(1)),
            ("O", self.apply_and_save),
            ("R", self.reset_adjustments),
            ("F", self.save_to_file),
            ("+", self.zoom_in),
            ("-", self.zoom_out),
            ("*", self.fit_preview),
            ("/", self.actual_size),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def add_adjustment_control(self, layout, row, name, minimum, maximum,
                               default, scale, decimals):
        initial_value = (
            self.remembered_values.get(name, default)
            if self.remember_adjustments else default
        )
        label = QLabel(name)
        label.setMinimumWidth(76)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(initial_value)
        slider.setFixedWidth(110)

        if decimals:
            value_input = QDoubleSpinBox()
            value_input.setDecimals(decimals)
            value_input.setRange(minimum / scale, maximum / scale)
            value_input.setSingleStep(0.05 if name == "Gamma" else 0.10)
            value_input.setValue(initial_value / scale)
        else:
            value_input = QSpinBox()
            value_input.setRange(minimum, maximum)
            value_input.setValue(initial_value)
        value_input.setKeyboardTracking(True)
        value_input.setFixedWidth(62 if decimals else 52)

        slider.valueChanged.connect(
            lambda value, control=name, divisor=scale:
                self.on_slider_value_changed(control, value, divisor)
        )
        value_input.valueChanged.connect(
            lambda value, control=name, multiplier=scale:
                self.on_value_input_changed(control, value, multiplier)
        )

        layout.addWidget(label, row, 0)
        layout.addWidget(slider, row, 1)
        layout.addWidget(value_input, row, 2)
        self.sliders[name] = slider
        self.value_inputs[name] = value_input
        self.control_scales[name] = scale

    def on_slider_value_changed(self, name, value, scale):
        value_input = self.value_inputs[name]
        value_input.blockSignals(True)
        value_input.setValue(value if scale == 1 else value / scale)
        value_input.blockSignals(False)
        self.on_adjustment_changed()

    def on_value_input_changed(self, name, value, scale):
        self.sliders[name].setValue(round(value * scale))

    def adjustment_values(self):
        values = {name: slider.value() for name, slider in self.sliders.items()}
        values.update(
            {name: checkbox.isChecked() for name, checkbox in self.effect_checks.items()}
        )
        return values

    def set_adjustment_values(self, values):
        defaults = self.adjustment_defaults()
        for name, slider in self.sliders.items():
            value = int(values.get(name, defaults[name]))
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            value_input = self.value_inputs[name]
            value_input.blockSignals(True)
            scale = self.control_scales[name]
            value_input.setValue(value if scale == 1 else value / scale)
            value_input.blockSignals(False)
        for name, checkbox in self.effect_checks.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(values.get(name, False)))
            checkbox.blockSignals(False)

    def neutral_adjustment_values(self):
        values = self.adjustment_defaults()
        values.update({name: False for name in self.TOGGLE_NAMES})
        return values

    def edit_signature(self):
        adjustments = tuple(
            (name, self.sliders[name].value())
            for column in self.CONTROL_COLUMNS
            for name, *_ in column
        )
        toggles = tuple(
            (name, self.effect_checks[name].isChecked())
            for name in self.TOGGLE_NAMES
        )
        target = self.target_dimensions()
        resize_state = None
        if target != self.original_pil.size:
            resize_state = (
                target,
                self.geometry_combo.currentData(),
                self.resample_combo.currentData(),
                self.padding_color.name()
                if self.geometry_combo.currentData() == "pad" else None,
            )
        return adjustments, toggles, resize_state

    def neutral_edit_signature(self):
        defaults = self.neutral_adjustment_values()
        adjustments = tuple(
            (name, defaults[name])
            for column in self.CONTROL_COLUMNS
            for name, *_ in column
        )
        toggles = tuple((name, False) for name in self.TOGGLE_NAMES)
        return adjustments, toggles, None

    def has_unsaved_changes(self):
        return self.edit_signature() != self.saved_signature

    def on_remember_toggled(self, enabled):
        if enabled:
            set_adjustment_settings(True, self.adjustment_values())
        else:
            set_adjustment_settings(False)

    def on_auto_name_toggled(self, enabled):
        self.auto_name_copies = bool(enabled)
        set_adjust_auto_name_copies(self.auto_name_copies)

    def done(self, result):
        if self.check_remember.isChecked():
            set_adjustment_settings(True, self.adjustment_values())
        super().done(result)
        
    def on_resize_mode_changed(self, index=None):
        self._updating_spins = True
        self.last_resize_axis = "width"
        if self.resize_mode_combo.currentData() == "percent":
            self.spin_width.setRange(1, 1000)
            self.spin_width.setValue(100)
            self.spin_height.setRange(1, 1000)
            self.spin_height.setValue(100)
        else:
            self.spin_width.setRange(1, 100000)
            self.spin_width.setValue(self.original_pil.width)
            self.spin_height.setRange(1, 100000)
            self.spin_height.setValue(self.original_pil.height)
        self._updating_spins = False
        self.on_resize_options_changed()

    def on_width_changed(self, value):
        if self._updating_spins:
            return
        self.last_resize_axis = "width"
        if self.geometry_combo.currentData() == "preserve":
            self._updating_spins = True
            if self.resize_mode_combo.currentData() == "percent":
                self.spin_height.setValue(value)
            else:
                ratio = self.original_pil.height / self.original_pil.width
                self.spin_height.setValue(max(1, round(value * ratio)))
            self._updating_spins = False
        self.on_resize_options_changed()

    def on_height_changed(self, value):
        if self._updating_spins:
            return
        self.last_resize_axis = "height"
        if self.geometry_combo.currentData() == "preserve":
            self._updating_spins = True
            if self.resize_mode_combo.currentData() == "percent":
                self.spin_width.setValue(value)
            else:
                ratio = self.original_pil.width / self.original_pil.height
                self.spin_width.setValue(max(1, round(value * ratio)))
            self._updating_spins = False
        self.on_resize_options_changed()

    def on_resize_options_changed(self, value=None):
        self.on_adjustment_changed()

    def on_aspect_changed(self, enabled):
        geometry = "preserve" if enabled else "stretch"
        index = self.geometry_combo.findData(geometry)
        if index >= 0 and self.geometry_combo.currentIndex() != index:
            self.geometry_combo.setCurrentIndex(index)

    def on_geometry_changed(self, index=None):
        geometry = self.geometry_combo.currentData()
        preserve = geometry == "preserve"
        self.check_aspect.blockSignals(True)
        self.check_aspect.setChecked(preserve)
        self.check_aspect.blockSignals(False)
        self.set_padding_controls_visible(geometry == "pad")
        if preserve:
            self.on_width_changed(self.spin_width.value())
        else:
            self.on_resize_options_changed()

    def on_resampling_changed(self, index=None):
        value = self.resample_combo.currentData() or "auto"
        self.remembered_resampling = value
        set_adjust_resampling(value)
        self.on_resize_options_changed()

    def set_padding_controls_visible(self, visible):
        self.padding_color_label.setVisible(bool(visible))
        self.padding_color_button.setVisible(bool(visible))

    def update_padding_color_button(self):
        color = self.padding_color.name()
        self.padding_color_button.setStyleSheet(
            f"QToolButton {{ background: {color}; border: 1px solid #aab4bc; }}"
            "QToolButton:hover { border: 2px solid #d9e4eb; }"
        )

    def choose_padding_color(self):
        color = QColorDialog.getColor(
            self.padding_color,
            self,
            "Choose Padding Color",
        )
        if not color.isValid():
            return
        self.padding_color = color
        self.update_padding_color_button()
        self.on_resize_options_changed()

    def resize_settings(self):
        return {
            "mode": self.resize_mode_combo.currentData(),
            "width": self.spin_width.value(),
            "height": self.spin_height.value(),
            "geometry": self.geometry_combo.currentData(),
            "aspect": self.geometry_combo.currentData() == "preserve",
            "resample": self.resample_combo.currentData(),
            "axis": self.last_resize_axis,
            "padding_color": self.padding_color.name(),
        }

    def apply_resize_settings(self, settings=None):
        self._updating_spins = True
        widgets = (
            self.resize_mode_combo, self.spin_width, self.spin_height,
            self.check_aspect, self.geometry_combo, self.resample_combo,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if not settings:
                mode = "pixels"
                width, height = self.original_pil.size
                geometry = "preserve"
                resample = self.remembered_resampling
                axis = "width"
                padding_color = "#000000"
            else:
                mode = settings.get("mode", "pixels")
                geometry = settings.get(
                    "geometry",
                    "preserve" if settings.get("aspect", True) else "stretch",
                )
                if self.geometry_combo.findData(geometry) < 0:
                    geometry = "preserve"
                resample = settings.get("resample", self.remembered_resampling)
                axis = settings.get("axis", "width")
                padding_color = settings.get("padding_color", "#000000")
                width = max(1, int(settings.get("width", self.original_pil.width)))
                height = max(1, int(settings.get("height", self.original_pil.height)))

            mode_index = self.resize_mode_combo.findData(mode)
            self.resize_mode_combo.setCurrentIndex(max(0, mode_index))
            if mode == "percent":
                self.spin_width.setRange(1, 1000)
                self.spin_height.setRange(1, 1000)
            else:
                self.spin_width.setRange(1, 100000)
                self.spin_height.setRange(1, 100000)
                if geometry == "preserve":
                    if axis == "height":
                        width = max(1, round(
                            height * self.original_pil.width / self.original_pil.height
                        ))
                    else:
                        height = max(1, round(
                            width * self.original_pil.height / self.original_pil.width
                        ))

            self.spin_width.setValue(width)
            self.spin_height.setValue(height)
            geometry_index = self.geometry_combo.findData(geometry)
            self.geometry_combo.setCurrentIndex(max(0, geometry_index))
            self.check_aspect.setChecked(geometry == "preserve")
            resample_index = self.resample_combo.findData(resample)
            self.resample_combo.setCurrentIndex(max(0, resample_index))
            self.last_resize_axis = axis if axis in ("width", "height") else "width"
            color = QColor(padding_color)
            self.padding_color = color if color.isValid() else QColor("#000000")
        finally:
            for widget in widgets:
                widget.blockSignals(False)
            self._updating_spins = False
        self.update_padding_color_button()
        self.set_padding_controls_visible(
            self.geometry_combo.currentData() == "pad"
        )

    def target_dimensions(self):
        width = self.original_pil.width
        height = self.original_pil.height
        if self.resize_mode_combo.currentData() == "percent":
            return (
                max(1, round(width * self.spin_width.value() / 100.0)),
                max(1, round(height * self.spin_height.value() / 100.0)),
            )
        return self.spin_width.value(), self.spin_height.value()

    @staticmethod
    def contained_dimensions(source_size, bounds):
        source_width, source_height = source_size
        bound_width, bound_height = bounds
        scale = min(bound_width / source_width, bound_height / source_height)
        return (
            max(1, min(bound_width, round(source_width * scale))),
            max(1, min(bound_height, round(source_height * scale))),
        )

    def output_dimensions(self):
        target = self.target_dimensions()
        if self.geometry_combo.currentData() == "fit":
            return self.contained_dimensions(self.original_pil.size, target)
        return target

    def selected_resampling_method(self, source_size=None, destination_size=None):
        key = self.resample_combo.currentData() or "auto"
        if key == "auto":
            source_size = source_size or self.original_pil.size
            destination_size = destination_size or self.output_dimensions()
            source_area = source_size[0] * source_size[1]
            destination_area = destination_size[0] * destination_size[1]
            return (
                Image.Resampling.LANCZOS
                if destination_area < source_area else Image.Resampling.BICUBIC
            )
        return self.RESAMPLING_METHODS.get(key, Image.Resampling.LANCZOS)

    def resample_image(self, image, destination_size):
        method = self.selected_resampling_method(image.size, destination_size)
        key = self.resample_combo.currentData() or "auto"
        resize_options = {}
        if (
            key == "auto" and method == Image.Resampling.LANCZOS and
            destination_size[0] < image.width and
            destination_size[1] < image.height
        ):
            resize_options["reducing_gap"] = 3.0
        resized = image.resize(destination_size, method, **resize_options)
        if key not in ("lanczos_sharper", "bicubic_sharper"):
            return resized

        alpha = resized.getchannel("A") if resized.mode == "RGBA" else None
        sharpened = resized.convert("RGB").filter(
            ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=2)
        )
        if alpha is not None:
            sharpened = Image.merge("RGBA", (*sharpened.split(), alpha))
        return sharpened

    def render_resized_image(self, image, target_size):
        target_width, target_height = target_size
        geometry = self.geometry_combo.currentData() or "preserve"

        if geometry in ("preserve", "stretch"):
            return self.resample_image(image, target_size)

        if geometry == "fit":
            fitted_size = self.contained_dimensions(image.size, target_size)
            return self.resample_image(image, fitted_size)

        if geometry == "fill":
            scale = max(target_width / image.width, target_height / image.height)
            cover_size = (
                max(target_width, math.ceil(image.width * scale)),
                max(target_height, math.ceil(image.height * scale)),
            )
            resized = self.resample_image(image, cover_size)
            left = max(0, (resized.width - target_width) // 2)
            top = max(0, (resized.height - target_height) // 2)
            return resized.crop(
                (left, top, left + target_width, top + target_height)
            )

        fitted_size = self.contained_dimensions(image.size, target_size)
        resized = self.resample_image(image, fitted_size)
        background = self.padding_color.getRgb()[:3]
        canvas_mode = "RGBA" if resized.mode == "RGBA" else "RGB"
        canvas_color = (*background, 255) if canvas_mode == "RGBA" else background
        canvas = Image.new(canvas_mode, target_size, canvas_color)
        position = (
            (target_width - resized.width) // 2,
            (target_height - resized.height) // 2,
        )
        if resized.mode == "RGBA":
            canvas.paste(resized, position, resized)
        else:
            canvas.paste(resized, position)
        return canvas

    def preview_output_dimensions(self):
        width, height = self.output_dimensions()
        scale = min(1.0, 1200.0 / width, 1200.0 / height)
        return max(1, round(width * scale)), max(1, round(height * scale))

    def reset_adjustments(self):
        defaults = {
            spec[0]: spec[3]
            for column in self.CONTROL_COLUMNS
            for spec in column
        }
        for name, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(defaults[name])
            slider.blockSignals(False)
            self.on_slider_value_changed(
                name, defaults[name], self.control_scales[name]
            )
        for checkbox in self.effect_checks.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
        self.on_adjustment_changed()

    def apply_adjustments(self, img):
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        img = img.convert("RGB")

        if self.effect_checks["Auto Contrast"].isChecked():
            img = ImageOps.autocontrast(img, cutoff=1)
        if self.effect_checks["Equalize"].isChecked():
            img = ImageOps.equalize(img)

        exposure = self.sliders["Exposure"].value() / 100.0
        if exposure != 0:
            img = ImageEnhance.Brightness(img).enhance(2.0 ** exposure)

        gamma = self.sliders["Gamma"].value() / 100.0
        if gamma != 1.0:
            gamma_lut = [
                round(255 * ((value / 255.0) ** (1.0 / gamma)))
                for value in range(256)
            ]
            img = img.point(gamma_lut * 3)

        sh = self.sliders["Shadows"].value()
        hl = self.sliders["Highlights"].value()
        if sh != 0 or hl != 0:
            tonal_lut = []
            for original in range(256):
                value = float(original)
                if sh > 0:
                    value += (255 - value) * (sh / 200.0) * (1 - value / 255.0)
                elif sh < 0:
                    value += value * (sh / 200.0) * (1 - value / 255.0)
                if hl > 0:
                    value += value * (hl / 200.0) * (value / 255.0)
                elif hl < 0:
                    value += (255 - value) * (hl / 200.0) * (value / 255.0)
                tonal_lut.append(round(max(0, min(255, value))))
            img = img.point(tonal_lut * 3)

        brightness = (self.sliders["Brightness"].value() / 100.0) + 1.0
        contrast = (self.sliders["Contrast"].value() / 100.0) + 1.0
        if brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)

        red = self.sliders["Red"].value()
        green = self.sliders["Green"].value()
        blue = self.sliders["Blue"].value()
        temperature = self.sliders["Temperature"].value()
        tint = self.sliders["Tint"].value()
        if red or green or blue or temperature or tint:
            gains = (
                max(0.0, 1.0 + red / 100.0 + temperature / 200.0 + tint / 400.0),
                max(0.0, 1.0 + green / 100.0 - tint / 200.0),
                max(0.0, 1.0 + blue / 100.0 - temperature / 200.0 + tint / 400.0),
            )
            channels = []
            for channel, gain in zip(img.split(), gains):
                lut = [round(max(0, min(255, value * gain))) for value in range(256)]
                channels.append(channel.point(lut))
            img = Image.merge("RGB", channels)

        hue = self.sliders["Hue"].value()
        if hue:
            hue_channel, saturation_channel, value_channel = img.convert("HSV").split()
            shift = round((hue / 360.0) * 256)
            hue_channel = hue_channel.point(
                [(value + shift) % 256 for value in range(256)]
            )
            img = Image.merge(
                "HSV", (hue_channel, saturation_channel, value_channel)
            ).convert("RGB")

        saturation = (self.sliders["Saturation"].value() / 100.0) + 1.0
        if saturation != 1.0:
            img = ImageEnhance.Color(img).enhance(saturation)

        if self.effect_checks["Grayscale"].isChecked():
            img = ImageOps.grayscale(img).convert("RGB")
        if self.effect_checks["Invert"].isChecked():
            img = ImageOps.invert(img)

        sharpness = (self.sliders["Sharpness"].value() / 100.0) + 1.0
        if sharpness != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(sharpness)

        if alpha is not None:
            img = Image.merge("RGBA", (*img.split(), alpha))
        return img

    def on_adjustment_changed(self):
        self.preview_timer.start()

    def apply_preview_adjustments(self):
        preview = self.apply_adjustments(self.preview_original_pil.copy())
        if self.target_dimensions() != self.original_pil.size:
            preview_size = self.preview_output_dimensions()
            preview = self.render_resized_image(preview, preview_size)
        self.preview_current_pil = preview
        self.update_preview()

    def update_preview(self):
        self.set_pil_to_pixmap(self.preview_current_pil)

    def show_original(self):
        self.set_pil_to_pixmap(self.preview_original_pil)
        
    def show_current(self):
        if self.preview_timer.isActive():
            self.preview_timer.stop()
            self.apply_preview_adjustments()
            return
        self.update_preview()

    def set_pil_to_pixmap(self, pil_img):
        old_rect = self.pixmap_item.boundingRect()
        old_center = self.view.mapToScene(self.view.viewport().rect().center())
        center_x = old_center.x() / old_rect.width() if old_rect.width() else 0.5
        center_y = old_center.y() / old_rect.height() if old_rect.height() else 0.5
        if pil_img.mode == "RGBA":
            data = pil_img.tobytes("raw", "RGBA")
            qim = QImage(data, pil_img.width, pil_img.height, pil_img.width * 4, QImage.Format.Format_RGBA8888)
        else:
            data = pil_img.tobytes("raw", "RGB")
            qim = QImage(data, pil_img.width, pil_img.height, pil_img.width * 3, QImage.Format.Format_RGB888)
            
        pix = QPixmap.fromImage(qim)
        self.pixmap_item.setPixmap(pix)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        if self.zoom_mode == "fit":
            self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            new_rect = self.pixmap_item.boundingRect()
            self.view.centerOn(
                new_rect.left() + (new_rect.width() * center_x),
                new_rect.top() + (new_rect.height() * center_y),
            )

    def zoom_by(self, factor):
        if self.pixmap_item.pixmap().isNull():
            return
        proposed = self.view.transform().m11() * factor
        if proposed < 0.02 or proposed > 64.0:
            return
        self.zoom_mode = "manual"
        self.view.scale(factor, factor)

    def zoom_in(self):
        self.zoom_by(1.10)

    def zoom_out(self):
        self.zoom_by(1 / 1.10)

    def fit_preview(self):
        if self.pixmap_item.pixmap().isNull():
            return
        self.zoom_mode = "fit"
        self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self):
        if self.pixmap_item.pixmap().isNull():
            return
        self.zoom_mode = "manual"
        self.view.resetTransform()
        self.view.centerOn(self.pixmap_item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom_mode == "fit" and not self.pixmap_item.pixmap().isNull():
            self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.fit_preview)

    def apply_and_save(self):
        if self.check_auto_name.isChecked():
            return self.save_auto_named_copy()

        msg = QMessageBox(self)
        msg.setWindowTitle("Save Image")
        msg.setText("Overwrite the original image or save the adjusted result as a copy?")
        overwrite_btn = msg.addButton("&Overwrite", QMessageBox.ButtonRole.AcceptRole)
        save_as_btn = msg.addButton("Save &As...", QMessageBox.ButtonRole.ActionRole)
        copy_btn = msg.addButton("_&adj Copy", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton("&Cancel", QMessageBox.ButtonRole.RejectRole)
        auto_check = QCheckBox("Use auto-named _adj copies for future O saves", msg)
        auto_check.setChecked(self.check_auto_name.isChecked())
        auto_check.toggled.connect(self.check_auto_name.setChecked)
        msg.setCheckBox(auto_check)
        msg.setDefaultButton(overwrite_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == overwrite_btn:
            return self.save_result_to_path(self.image_path)
        if clicked == save_as_btn:
            return self.save_to_file()
        if clicked == copy_btn:
            return self.save_auto_named_copy()
        if clicked == cancel_btn:
            return False
        return False

    def render_final_image(self):
        target_size = self.target_dimensions()
        final_img = self.apply_adjustments(self.original_pil.copy())
        if target_size != self.original_pil.size:
            final_img = self.render_resized_image(final_img, target_size)
        return final_img

    def save_result_to_path(self, output_path):
        if not output_path:
            return False
        try:
            self.render_final_image().save(output_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save image: {e}")
            return False

        self.saved_any = True
        self.saved_signature = self.edit_signature()
        self.image_saved.emit(output_path)
        return True

    def unique_adjusted_path(self):
        folder, name = os.path.split(self.image_path)
        stem, extension = os.path.splitext(name)
        candidate = os.path.join(folder, f"{stem}_adj{extension}")
        counter = 2
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{stem}_adj{counter}{extension}")
            counter += 1
        return candidate

    def save_auto_named_copy(self):
        return self.save_result_to_path(self.unique_adjusted_path())

    def save_to_file(self):
        filters = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All Files (*)"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Adjusted Image",
            self.unique_adjusted_path(),
            filters,
        )
        if not output_path:
            return False
        return self.save_result_to_path(output_path)

    def adjacent_path(self, direction):
        index = self.navigation_positions.get(self.image_path)
        if index is None or direction not in (-1, 1):
            return None
        candidate_index = index + direction
        while 0 <= candidate_index < len(self.navigation_paths):
            candidate = self.navigation_paths[candidate_index]
            if os.path.isfile(candidate):
                return candidate
            candidate_index += direction
        return None

    def update_navigation_buttons(self):
        if not hasattr(self, "btn_previous"):
            return
        self.btn_previous.setEnabled(self.adjacent_path(-1) is not None)
        self.btn_next.setEnabled(self.adjacent_path(1) is not None)

    def confirm_navigation(self):
        if not self.has_unsaved_changes():
            return True
        if AdjustBoard._session_navigation_choice == "save":
            saved = self.apply_and_save()
            if not saved:
                AdjustBoard._session_navigation_choice = None
            return saved
        if AdjustBoard._session_navigation_choice == "discard":
            return True

        msg = QMessageBox(self)
        msg.setWindowTitle("Save Changes?")
        msg.setText("Save adjustment changes before moving to another image?")
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
            saved = self.apply_and_save()
            if saved and remember_check.isChecked():
                AdjustBoard._session_navigation_choice = "save"
            return saved
        if clicked == discard_btn:
            if remember_check.isChecked():
                AdjustBoard._session_navigation_choice = "discard"
            return True
        return False

    def load_image(self, image_path):
        adjustment_state = (
            self.adjustment_values()
            if self.check_remember.isChecked() else self.neutral_adjustment_values()
        )
        resize_state = (
            self.resize_settings()
            if self.check_remember_resize.isChecked() else None
        )
        try:
            new_original = self.read_image(image_path)
        except Exception as e:
            QMessageBox.warning(self, "Open Image", f"Failed to open image: {e}")
            return False

        self.preview_timer.stop()
        self.image_path = image_path
        self.original_pil = new_original
        self.build_preview_source()
        self.set_adjustment_values(adjustment_state)
        self.apply_resize_settings(resize_state)
        self.saved_signature = self.neutral_edit_signature()
        self.zoom_mode = "fit"
        self.apply_preview_adjustments()
        self.setWindowTitle(f"Adjust Colors & Size - {os.path.basename(image_path)}")
        self.update_navigation_buttons()
        self.image_changed.emit(image_path)
        return True

    def open_adjacent_image(self, direction):
        next_path = self.adjacent_path(direction)
        if not next_path:
            return False
        if not self.confirm_navigation():
            return False
        return self.load_image(next_path)

    def eventFilter(self, obj, event):
        if obj == self.view.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_in()
                elif delta < 0:
                    self.zoom_out()
                else:
                    return True
                event.accept()
                return True
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                direction = 1 if event.angleDelta().y() < 0 else -1
                self.open_adjacent_image(direction)
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
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
            return
        if key == Qt.Key.Key_PageUp:
            self.open_adjacent_image(-1)
            event.accept()
            return
        if key == Qt.Key.Key_PageDown:
            self.open_adjacent_image(1)
            event.accept()
            return
        if plain_key:
            zoom_actions = {
                Qt.Key.Key_Plus: self.zoom_in,
                Qt.Key.Key_Minus: self.zoom_out,
                Qt.Key.Key_Asterisk: self.fit_preview,
                Qt.Key.Key_Slash: self.actual_size,
            }
            zoom_action = zoom_actions.get(key)
            if zoom_action is not None:
                zoom_action()
                event.accept()
                return
            actions = {
                "p": lambda: self.open_adjacent_image(-1),
                "n": lambda: self.open_adjacent_image(1),
                "o": self.apply_and_save,
                "r": self.reset_adjustments,
                "f": self.save_to_file,
                "+": self.zoom_in,
                "-": self.zoom_out,
                "*": self.fit_preview,
                "/": self.actual_size,
            }
            action = actions.get(text)
            if action is not None:
                action()
                event.accept()
                return
        super().keyPressEvent(event)
