import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QSlider, QGroupBox, QFormLayout,
                             QCheckBox, QRadioButton, QFileDialog, QMessageBox, QProgressBar, QWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from utils.animated_webp import save_animated_webp
from utils.atomic_output import staged_output
from utils.file_ops import (
    get_convert_appendix, get_format_quality, get_image_settings,
    set_convert_appendix, set_format_quality,
)
from utils.image_loading import open_limited_pil_image
from utils.comfy_webp import webp_metadata, save_verified_webp
from PIL import Image

def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def same_file(source, target):
    if path_key(source) == path_key(target):
        return True
    try:
        return os.path.samefile(source, target)
    except OSError:
        return False


def build_conversion_plan(files, target_folder, appendix, format_str):
    plan = []
    targets = set()
    sources = {path_key(path) for path in files}
    for source in files:
        folder, name = os.path.split(source)
        stem, extension = os.path.splitext(name)
        output_ext = format_str.lower() if format_str else extension[1:].lower()
        target = os.path.join(target_folder or folder, f"{stem}{appendix}.{output_ext}")
        key = path_key(target)
        if key in targets:
            raise ValueError(f"Multiple selected images would write to {target}. Choose another format or convert them separately.")
        if key in sources and key != path_key(source):
            raise ValueError(f"The output {target} would overwrite another selected source. Choose a different appendix or output folder.")
        targets.add(key)
        plan.append((source, target))
    return plan


class ConvertWorker(QThread):
    progress = pyqtSignal(int, int) # current, total
    finished = pyqtSignal(int, int) # success, total
    error = pyqtSignal(str, str) # filepath, error_msg

    def __init__(self, files, target_folder, appendix, format_str, rotate_op, quality, keep_date, delete_orig,
                 keep_comfy=False):
        super().__init__()
        self.files = files
        self.target_folder = target_folder
        self.appendix = appendix
        self.format_str = format_str
        self.rotate_op = rotate_op
        self.quality = quality
        self.keep_date = keep_date
        self.delete_orig = delete_orig
        self.keep_comfy = bool(keep_comfy and format_str == "WebP")
        self.decoded_limit_mb = get_image_settings()["max_decoded_image_mb"]
        self.changed_paths = []
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        success_count = 0
        total = len(self.files)
        try:
            plan = build_conversion_plan(self.files, self.target_folder, self.appendix, self.format_str)
        except ValueError as error:
            self.error.emit("", str(error))
            self.finished.emit(0, total)
            return
        
        for i, (file_path, new_path) in enumerate(plan):
            if not self._is_running:
                break
                
            try:
                source_stat = os.stat(file_path) if self.keep_date else None
                delete_source = self.delete_orig and not same_file(file_path, new_path)
                self.convert_file(file_path, new_path)
                self.changed_paths.append(new_path)
                    
                if source_stat is not None:
                    try:
                        os.utime(new_path, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
                    except Exception:
                        pass
                        
                if delete_source:
                    try:
                        os.remove(file_path)
                        self.changed_paths.append(file_path)
                    except Exception:
                        pass
                        
                success_count += 1
            except Exception as e:
                self.error.emit(file_path, str(e))
                
            self.progress.emit(i + 1, total)
            
        self.finished.emit(success_count, total)

    def convert_file(self, file_path, new_path):
        if self.keep_comfy:
            with open_limited_pil_image(file_path, self.decoded_limit_mb) as opened:
                if getattr(opened, "n_frames", 1) != 1:
                    raise ValueError("The metadata-preserving WebP conversion requires a single-frame image.")
                options, tags = webp_metadata(opened)
                has_alpha = "A" in opened.getbands() or "transparency" in opened.info
                img = opened.convert("RGBA" if has_alpha else "RGB")
            save_verified_webp(self.apply_rotation(img), new_path, self.quality, options, tags,
                               verify_pixels=self.delete_orig)
            return

        with staged_output(new_path) as temp_path:
            with open_limited_pil_image(file_path, self.decoded_limit_mb) as opened:
                output_format = (self.format_str or Image.registered_extensions().get(
                    os.path.splitext(new_path)[1].lower(), ""
                )).upper()
                if getattr(opened, "n_frames", 1) > 1:
                    if opened.format not in ("GIF", "WEBP") or output_format != "WEBP":
                        raise ValueError(
                            f"Multi-frame {opened.format} to {output_format} is unsupported. "
                            "Batch Convert supports animated GIF or WebP to WebP."
                        )
                    transform = self.apply_rotation if self.rotate_op else None
                    save_animated_webp(
                        opened, temp_path, self.quality, transform, limit_mb=self.decoded_limit_mb,
                    )
                    return
                img = self.apply_rotation(opened.copy())
                exif = opened.info.get("exif")
            self.save_still_image(img, temp_path, exif)
            with Image.open(temp_path) as saved:
                if saved.format != output_format or saved.size != img.size:
                    raise ValueError("The encoded image format or dimensions differ from the requested output.")
                saved.load()

    def save_still_image(self, img, target, exif):
        if self.format_str == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        elif img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        options = {}
        if self.format_str in ("JPEG", "WebP"):
            options["quality"] = self.quality
            if exif:
                options["exif"] = exif
        img.save(target, format=self.format_str or None, **options)

    def apply_rotation(self, img):
        if self.rotate_op == "right":
            return img.rotate(-90, expand=True)
        if self.rotate_op == "left":
            return img.rotate(90, expand=True)
        if self.rotate_op == "180":
            return img.rotate(180, expand=True)
        if self.rotate_op == "flip_h":
            return img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self.rotate_op == "flip_v":
            return img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return img


class ConvertDialog(QDialog):
    suppress_overwrite_warning = False

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Convert / Rotate")
        self.resize(520, 500)
        self.files = files
        self.changed_paths = []
        self.error_examples = []
        self.stop_requested = False
        
        layout = QVBoxLayout(self)
        
        # Output Group
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        
        folder_layout = QHBoxLayout()
        self.radio_source = QRadioButton("Source folder")
        self.radio_source.setChecked(True)
        self.radio_custom = QRadioButton("Custom folder:")
        self.custom_folder_edit = QLineEdit()
        self.custom_folder_edit.setEnabled(False)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setEnabled(False)
        
        self.radio_source.toggled.connect(self.on_radio_toggled)
        self.browse_btn.clicked.connect(self.browse_folder)
        
        folder_layout.addWidget(self.radio_source)
        folder_layout.addWidget(self.radio_custom)
        folder_layout.addWidget(self.custom_folder_edit)
        folder_layout.addWidget(self.browse_btn)
        
        output_layout.addLayout(folder_layout)
        
        form_layout = QFormLayout()
        self.appendix_edit = QLineEdit(get_convert_appendix())
        form_layout.addRow("Filename Appendix:", self.appendix_edit)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Don't change", "PNG", "JPEG", "WebP"])
        self.format_combo.currentIndexChanged.connect(self.on_format_changed)
        form_layout.addRow("Format:", self.format_combo)

        self.rotate_combo = QComboBox()
        self.rotate_combo.addItem("Don't change", None)
        self.rotate_combo.addItem("Rotate 90° right", "right")
        self.rotate_combo.addItem("Rotate 90° left", "left")
        self.rotate_combo.addItem("Rotate 180°", "180")
        self.rotate_combo.addItem("Flip horizontal", "flip_h")
        self.rotate_combo.addItem("Flip vertical", "flip_v")
        form_layout.addRow("Rotate / Flip:", self.rotate_combo)
        
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_label = QLabel("90")
        
        qual_layout = QHBoxLayout()
        qual_layout.addWidget(self.quality_slider)
        qual_layout.addWidget(self.quality_label)
        self.quality_container = QWidget()
        self.quality_container.setLayout(qual_layout)
        form_layout.addRow("Quality:", self.quality_container)
        
        self.quality_slider.valueChanged.connect(self.on_quality_changed)
        
        output_layout.addLayout(form_layout)
        layout.addWidget(output_group)
        
        # Options Group
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        self.keep_date_cb = QCheckBox("Keep original date/time attributes")
        self.keep_comfy_cb = QCheckBox("Keep ComfyUI workflow and compact prompt summary")
        self.keep_comfy_cb.setToolTip(
            "Converts PNG workflow and prompt graphs to WebP metadata and keeps a summary "
            "for the standalone prompt extractor. Other still images can be included. "
            "Animated inputs are skipped."
        )
        self.delete_orig_cb = QCheckBox("Delete original")
        self.delete_orig_cb.setProperty("destructive", True)
        
        options_layout.addWidget(self.keep_date_cb)
        options_layout.addWidget(self.keep_comfy_cb)
        options_layout.addWidget(self.delete_orig_cb)
        layout.addWidget(options_group)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.status_label = QLabel(f"{len(self.files)} files selected")
        btn_layout.addWidget(self.status_label)
        btn_layout.addStretch()
        
        self.convert_btn = QPushButton("Execute")
        self.close_btn = QPushButton("Close")
        
        self.convert_btn.clicked.connect(self.start_conversion)
        self.close_btn.clicked.connect(self.close_or_stop)
        
        btn_layout.addWidget(self.convert_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)
        
        self.worker = None
        self.on_format_changed()
        
    def on_radio_toggled(self):
        is_custom = self.radio_custom.isChecked()
        self.custom_folder_edit.setEnabled(is_custom)
        self.browse_btn.setEnabled(is_custom)
        
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.custom_folder_edit.setText(folder)
            
    def on_format_changed(self):
        fmt = self.format_combo.currentText()
        self.keep_comfy_cb.setEnabled(fmt == "WebP")
        if fmt in ("JPEG", "WebP"):
            self.quality_container.show()
            q = get_format_quality(fmt)
            self.quality_slider.setValue(q)
            self.quality_label.setText(str(q))
        else:
            self.quality_container.hide()
            
    def on_quality_changed(self, value):
        self.quality_label.setText(str(value))
        
    def start_conversion(self):
        fmt_text = self.format_combo.currentText()
        fmt = None if fmt_text == "Don't change" else fmt_text
        rotate_op = self.rotate_combo.currentData()
        if fmt is None and rotate_op is None:
            QMessageBox.information(self, "Nothing To Do", "Choose a format conversion, a rotate/flip operation, or both.")
            return

        if self.delete_orig_cb.isChecked():
            reply = QMessageBox.warning(
                self, "Warning", 
                "You have selected 'Delete original'. The original files will be deleted after conversion. Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
                
        target_folder = self.custom_folder_edit.text() if self.radio_custom.isChecked() else None
        if target_folder and not os.path.exists(target_folder):
            QMessageBox.warning(self, "Error", "Selected custom folder does not exist.")
            return
            
        appendix = self.appendix_edit.text()
        quality = self.quality_slider.value()
        try:
            plan = build_conversion_plan(self.files, target_folder, appendix, fmt)
        except ValueError as error:
            QMessageBox.warning(self, "Conflicting output names", str(error))
            return
        
        # Save config preferences
        set_convert_appendix(appendix)
        if fmt in ("JPEG", "WebP"):
            set_format_quality(fmt, quality)
            
        # Check for potential overwrites
        overwrites = []
        for file_path, new_path in plan:
            # If it's literally the same file being targeted, or if it already exists
            if os.path.exists(new_path):
                overwrites.append(os.path.basename(new_path))
                
        if overwrites and not ConvertDialog.suppress_overwrite_warning:
            if not self.confirm_overwrite_warning(overwrites):
                return
                
        self.convert_btn.setEnabled(False)
        self.close_btn.setText("Stop after this file")
        self.error_examples.clear()
        self.progress_bar.setMaximum(len(self.files))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.worker = ConvertWorker(
            self.files, target_folder, appendix, fmt, rotate_op, quality, 
            self.keep_date_cb.isChecked(), self.delete_orig_cb.isChecked(),
            keep_comfy=self.keep_comfy_cb.isEnabled() and self.keep_comfy_cb.isChecked()
        )
        self.changed_paths = self.worker.changed_paths
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        
    def on_progress(self, current, total):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processed {current} / {total}")
        
    def on_error(self, file_path, msg):
        if len(self.error_examples) < 5:
            self.error_examples.append(f"{os.path.basename(file_path)}: {msg}" if file_path else msg)
        print(f"Failed to convert {file_path}: {msg}")
        
    def on_finished(self, success_count, total):
        if self.worker is not None:
            self.worker.wait()
        self.worker = None
        message = f"Converted {success_count} of {total} files."
        if self.error_examples:
            message += "\n\n" + "\n".join(self.error_examples)
        QMessageBox.information(self, "Stopped" if self.stop_requested else "Done", message)
        self.accept()

    def close_or_stop(self):
        if self.worker is None:
            self.reject()
        else:
            self.stop_requested = True
            self.worker.stop()
            self.close_btn.setEnabled(False)

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def confirm_overwrite_warning(self, overwrites):
        msg = QMessageBox(self)
        msg.setWindowTitle("Overwrite Warning")
        msg.setText(f"This operation will overwrite {len(overwrites)} existing files (e.g. {overwrites[0]}). Proceed?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        dont_warn_cb = QCheckBox("Don't warn again this session")
        msg.setCheckBox(dont_warn_cb)
        reply = msg.exec()
        if reply == QMessageBox.StandardButton.Yes and dont_warn_cb.isChecked():
            ConvertDialog.suppress_overwrite_warning = True
        return reply == QMessageBox.StandardButton.Yes
