import os
import time
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QSlider, QGroupBox, QFormLayout,
                             QCheckBox, QRadioButton, QFileDialog, QMessageBox, QProgressBar, QWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from utils.file_ops import get_format_quality, set_format_quality, get_convert_appendix, set_convert_appendix
from PIL import Image

class ConvertWorker(QThread):
    progress = pyqtSignal(int, int) # current, total
    finished = pyqtSignal(int, int) # success, total
    error = pyqtSignal(str, str) # filepath, error_msg

    def __init__(self, files, target_folder, appendix, format_str, rotate_op, quality, keep_date, delete_orig):
        super().__init__()
        self.files = files
        self.target_folder = target_folder
        self.appendix = appendix
        self.format_str = format_str
        self.rotate_op = rotate_op
        self.quality = quality
        self.keep_date = keep_date
        self.delete_orig = delete_orig
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        success_count = 0
        total = len(self.files)
        
        for i, file_path in enumerate(self.files):
            if not self._is_running:
                break
                
            folder, name = os.path.split(file_path)
            basename, original_ext = os.path.splitext(name)
            
            dest_folder = self.target_folder if self.target_folder else folder
            output_ext = self.format_str.lower() if self.format_str else original_ext[1:].lower()
            new_name = f"{basename}{self.appendix}.{output_ext}"
            new_path = os.path.join(dest_folder, new_name)
            
            try:
                with Image.open(file_path) as opened:
                    img = opened.copy()
                    exif = opened.info.get('exif')

                img = self.apply_rotation(img)
                
                # Handling modes
                save_format = self.format_str or None
                if save_format == "JPEG" and img.mode in ('RGBA', 'LA', 'P'):
                    # Create a white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        background.paste(img, mask=img.split()[3]) # paste using alpha channel as mask
                    elif img.mode == 'LA':
                        background.paste(img, mask=img.split()[1])
                    else:
                        img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode == 'P':
                    img = img.convert('RGB')
                
                if save_format in ("JPEG", "WebP"):
                    if exif:
                        img.save(new_path, format=save_format, quality=self.quality, exif=exif)
                    else:
                        img.save(new_path, format=save_format, quality=self.quality)
                else:
                    if save_format:
                        img.save(new_path, format=save_format)
                    else:
                        img.save(new_path)
                    
                if self.keep_date:
                    try:
                        stat = os.stat(file_path)
                        os.utime(new_path, (stat.st_atime, stat.st_mtime))
                    except Exception:
                        pass
                        
                if self.delete_orig and file_path != new_path:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                        
                success_count += 1
            except Exception as e:
                self.error.emit(file_path, str(e))
                
            self.progress.emit(i + 1, total)
            
        self.finished.emit(success_count, total)

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
        self.delete_orig_cb = QCheckBox("Delete original")
        self.delete_orig_cb.setProperty("destructive", True)
        
        options_layout.addWidget(self.keep_date_cb)
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
        self.close_btn.clicked.connect(self.reject)
        
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
        
        # Save config preferences
        set_convert_appendix(appendix)
        if fmt in ("JPEG", "WebP"):
            set_format_quality(fmt, quality)
            
        # Check for potential overwrites
        overwrites = []
        for file_path in self.files:
            folder, name = os.path.split(file_path)
            basename, original_ext = os.path.splitext(name)
            dest = target_folder if target_folder else folder
            output_ext = fmt.lower() if fmt else original_ext[1:].lower()
            new_name = f"{basename}{appendix}.{output_ext}"
            new_path = os.path.join(dest, new_name)
            
            # If it's literally the same file being targeted, or if it already exists
            if os.path.exists(new_path):
                overwrites.append(new_name)
                
        if overwrites and not ConvertDialog.suppress_overwrite_warning:
            if not self.confirm_overwrite_warning(overwrites):
                return
                
        self.convert_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(self.files))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.worker = ConvertWorker(
            self.files, target_folder, appendix, fmt, rotate_op, quality, 
            self.keep_date_cb.isChecked(), self.delete_orig_cb.isChecked()
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        
    def on_progress(self, current, total):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processed {current} / {total}")
        
    def on_error(self, file_path, msg):
        print(f"Failed to convert {file_path}: {msg}")
        
    def on_finished(self, success_count, total):
        QMessageBox.information(self, "Done", f"Processed {success_count} of {total} files successfully.")
        self.accept()

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
