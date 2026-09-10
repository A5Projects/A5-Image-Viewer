import os
import tempfile
import time
import uuid

from PIL import Image, PngImagePlugin
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')

ROTATE_OPERATIONS = (
    ("Rotate 90 degrees right", "right"),
    ("Rotate 90 degrees left", "left"),
    ("Rotate 180 degrees", "180"),
    ("Flip horizontal", "flip_h"),
    ("Flip vertical", "flip_v"),
)


def rename_with_sharing_retry(source, destination, timeout_seconds=10.0):
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    delay = 0.05
    while True:
        try:
            os.rename(source, destination)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in (32, 33):
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(0.25, delay * 1.5)


def parse_rename_template(template):
    tokens = []
    literal = []
    number_width = None
    index = 0

    def flush_literal():
        if literal:
            tokens.append(("literal", "".join(literal)))
            literal.clear()

    while index < len(template):
        char = template[index]
        if char == "\\" and index + 1 < len(template) and template[index + 1] == "#":
            literal.append("#")
            index += 2
            continue
        if char == "*":
            flush_literal()
            tokens.append(("original", None))
            index += 1
            continue
        if char == "#":
            flush_literal()
            end = index
            while end < len(template) and template[end] == "#":
                end += 1
            if number_width is not None:
                raise ValueError("Use only one contiguous run of # characters.")
            number_width = end - index
            tokens.append(("number", number_width))
            index = end
            continue
        literal.append(char)
        index += 1

    flush_literal()
    return tokens, number_width


def render_rename_template(tokens, original_basename, number):
    parts = []
    for kind, value in tokens:
        if kind == "literal":
            parts.append(value)
        elif kind == "original":
            parts.append(original_basename)
        elif kind == "number":
            parts.append(str(number).zfill(value))
    return "".join(parts)


def escape_rename_template_literal(text):
    return text.replace("#", r"\#")


def validate_windows_filename(filename):
    if not filename:
        return "The generated filename is empty."
    if filename.endswith((" ", ".")):
        return "Windows filenames cannot end with a space or period."
    if any(char in WINDOWS_INVALID_CHARS or ord(char) < 32 for char in filename):
        return "The generated filename contains a character Windows does not allow."
    basename = filename.split(".", 1)[0].upper()
    if basename in WINDOWS_RESERVED_NAMES:
        return f"{basename} is a reserved Windows filename."
    return None


def build_batch_rename_plan(paths, template, start_number, existing_unselected=None):
    if not paths:
        return [], ["No image files are selected."], False

    try:
        tokens, number_width = parse_rename_template(template)
    except ValueError as error:
        return [], [str(error)], False

    folders = {os.path.normcase(os.path.abspath(os.path.dirname(path))) for path in paths}
    if len(folders) != 1:
        return [], ["All selected files must be in the same folder."], number_width is not None

    folder = os.path.dirname(os.path.abspath(paths[0]))
    selected_names = {os.path.basename(path).casefold() for path in paths}
    if existing_unselected is None:
        try:
            existing_unselected = {
                entry.name.casefold()
                for entry in os.scandir(folder)
                if entry.name.casefold() not in selected_names
            }
        except OSError as error:
            return [], [f"Could not inspect the folder: {error}"], number_width is not None

    plan = []
    errors = []
    target_names = {}
    for offset, old_path in enumerate(paths):
        old_name = os.path.basename(old_path)
        original_basename, extension = os.path.splitext(old_name)
        new_basename = render_rename_template(tokens, original_basename, start_number + offset)
        new_name = new_basename + extension
        new_path = os.path.join(folder, new_name)
        row_error = validate_windows_filename(new_name)
        folded = new_name.casefold()
        if row_error:
            errors.append(f"{old_name}: {row_error}")
        elif folded in target_names:
            errors.append(f"{old_name}: duplicates the target name for {target_names[folded]}.")
        elif folded in existing_unselected:
            errors.append(f"{old_name}: {new_name} already exists.")
        target_names[folded] = old_name
        plan.append((old_path, new_path))

    return plan, errors, number_width is not None


class BatchRenameWorker(QThread):
    progress = pyqtSignal(int, int)
    result_ready = pyqtSignal(object, object)

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = [(old, new) for old, new in plan if old != new]

    def run(self):
        total = len(self.plan)
        if total == 0:
            self.result_ready.emit({}, [])
            return

        temporary_paths = {}
        moved_to_temporary = []
        finalized = []
        errors = []

        try:
            for old_path, new_path in self.plan:
                folder = os.path.dirname(old_path)
                while True:
                    temp_path = os.path.join(folder, f".a5rename-{uuid.uuid4().hex}.tmp")
                    if not os.path.exists(temp_path):
                        break
                rename_with_sharing_retry(old_path, temp_path)
                temporary_paths[old_path] = temp_path
                moved_to_temporary.append(old_path)

            for position, (old_path, new_path) in enumerate(self.plan, 1):
                rename_with_sharing_retry(temporary_paths[old_path], new_path)
                finalized.append((old_path, new_path))
                self.progress.emit(position, total)
        except Exception as error:
            errors.append(str(error))
            for old_path, new_path in reversed(finalized):
                temp_path = temporary_paths[old_path]
                try:
                    rename_with_sharing_retry(new_path, temp_path)
                except Exception as rollback_error:
                    errors.append(f"Could not prepare {new_path} for rollback: {rollback_error}")
            for old_path in reversed(moved_to_temporary):
                temp_path = temporary_paths[old_path]
                if not os.path.exists(temp_path):
                    continue
                try:
                    rename_with_sharing_retry(temp_path, old_path)
                except Exception as rollback_error:
                    errors.append(f"Could not restore {old_path}: {rollback_error}")
            self.result_ready.emit({}, errors)
            return

        self.result_ready.emit(dict(self.plan), [])


class BatchRenameDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.rename_mapping = {}
        self.worker = None
        self.folder_scan_error = None
        self.existing_unselected = self.collect_existing_unselected()
        self.setWindowTitle("Batch Rename")
        self.resize(680, 440)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.template_edit = QLineEdit("*")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999_999_999)
        self.start_spin.setValue(1)
        form.addRow("Template:", self.template_edit)
        form.addRow("Start at:", self.start_spin)
        layout.addLayout(form)

        help_label = QLabel(r"Use * for the original name, # for numbering, and \# for a literal #.")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.table = QTableWidget(len(self.paths), 2)
        self.table.setHorizontalHeaderLabels(["Old name", "New name"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.use_filename_as_template)
        for row, path in enumerate(self.paths):
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(path)))
            self.table.setItem(row, 1, QTableWidgetItem(""))
        layout.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.execute_button = QPushButton("Execute")
        self.execute_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.execute_button.clicked.connect(self.start_rename)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.execute_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.template_edit.textChanged.connect(self.update_preview)
        self.start_spin.valueChanged.connect(self.update_preview)
        self.update_preview()

    def collect_existing_unselected(self):
        if not self.paths:
            return set()
        selected_names = {os.path.basename(path).casefold() for path in self.paths}
        folder = os.path.dirname(os.path.abspath(self.paths[0]))
        try:
            return {
                entry.name.casefold()
                for entry in os.scandir(folder)
                if entry.name.casefold() not in selected_names
            }
        except OSError as error:
            self.folder_scan_error = f"Could not inspect the folder: {error}"
            return set()

    def update_preview(self):
        plan, errors, has_number = build_batch_rename_plan(
            self.paths,
            self.template_edit.text(),
            self.start_spin.value(),
            self.existing_unselected,
        )
        if self.folder_scan_error:
            errors.insert(0, self.folder_scan_error)
        self.start_spin.setEnabled(has_number)

        for row, old_path in enumerate(self.paths):
            old_name = os.path.basename(old_path)
            new_name = os.path.basename(plan[row][1]) if row < len(plan) else ""
            self.table.item(row, 0).setText(old_name)
            self.table.item(row, 1).setText(new_name)

        changed = bool(plan) and any(old != new for old, new in plan)
        self.execute_button.setEnabled(not errors and changed)
        if self.status_label.property("error") != bool(errors):
            self.status_label.setProperty("error", bool(errors))
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
        if errors:
            self.status_label.setText(errors[0])
        elif not changed:
            self.status_label.setText("The generated names are unchanged.")
        else:
            self.status_label.setText(f"{len(plan)} files")

    def use_filename_as_template(self, row, column):
        if row < 0 or row >= len(self.paths):
            return
        basename = os.path.splitext(os.path.basename(self.paths[row]))[0]
        self.template_edit.setText(escape_rename_template_literal(basename))
        self.template_edit.setFocus()
        self.template_edit.selectAll()

    def start_rename(self):
        plan, errors, _ = build_batch_rename_plan(
            self.paths,
            self.template_edit.text(),
            self.start_spin.value(),
            self.existing_unselected,
        )
        if self.folder_scan_error:
            errors.insert(0, self.folder_scan_error)
        if errors:
            QMessageBox.warning(self, "Batch Rename", errors[0])
            return
        if not any(old != new for old, new in plan):
            return

        self.execute_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.template_edit.setEnabled(False)
        self.start_spin.setEnabled(False)
        self.progress_bar.setRange(0, len([1 for old, new in plan if old != new]))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.worker = BatchRenameWorker(plan, self)
        self.worker.progress.connect(lambda current, total: self.progress_bar.setValue(current))
        self.worker.result_ready.connect(self.on_rename_finished)
        self.worker.start(QThread.Priority.LowestPriority)

    def on_rename_finished(self, mapping, errors):
        if self.worker is not None:
            self.worker.wait()
        self.worker = None
        if errors:
            self.execute_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.template_edit.setEnabled(True)
            self.update_preview()
            QMessageBox.warning(self, "Batch Rename", "\n".join(errors[:5]))
            return
        self.rename_mapping = mapping
        self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return
        super().reject()


def _image_save_options(opened, source_format):
    options = {}
    try:
        exif = opened.getexif()
        if exif:
            exif[274] = 1
            if source_format in {"JPEG", "TIFF", "PNG", "WEBP"}:
                options["exif"] = exif.tobytes()
    except Exception:
        pass

    if opened.info.get("icc_profile"):
        options["icc_profile"] = opened.info["icc_profile"]
    if opened.info.get("dpi"):
        options["dpi"] = opened.info["dpi"]
    if opened.info.get("comment") and source_format == "JPEG":
        options["comment"] = opened.info["comment"]
    if source_format == "PNG":
        png_info = PngImagePlugin.PngInfo()
        for key, value in opened.info.items():
            if isinstance(value, str):
                png_info.add_text(key, value)
        if getattr(png_info, "chunks", None):
            options["pnginfo"] = png_info
    if source_format == "JPEG":
        options["quality"] = 95
    return options


def transform_image_atomic(file_path, operation):
    folder = os.path.dirname(file_path)
    extension = os.path.splitext(file_path)[1]
    temp_path = None
    try:
        with Image.open(file_path) as opened:
            source_format = opened.format
            frame_count = int(getattr(opened, "n_frames", 1))
            if frame_count > 1:
                raise ValueError("Animated or multi-frame images are not changed by batch rotate.")
            opened.load()
            save_options = _image_save_options(opened, source_format)
            if operation == "right":
                transformed = opened.transpose(Image.Transpose.ROTATE_270)
            elif operation == "left":
                transformed = opened.transpose(Image.Transpose.ROTATE_90)
            elif operation == "180":
                transformed = opened.transpose(Image.Transpose.ROTATE_180)
            elif operation == "flip_h":
                transformed = opened.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            elif operation == "flip_v":
                transformed = opened.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            else:
                raise ValueError("Unknown rotate/flip operation.")

            handle, temp_path = tempfile.mkstemp(
                prefix=".a5rotate-",
                suffix=extension,
                dir=folder,
            )
            os.close(handle)
            transformed.save(temp_path, format=source_format, **save_options)
        os.replace(temp_path, file_path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


class BatchRotateWorker(QThread):
    progress = pyqtSignal(int, int)
    result_ready = pyqtSignal(object, object)

    def __init__(self, paths, operation, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.operation = operation

    def run(self):
        successful = []
        errors = {}
        total = len(self.paths)
        for position, file_path in enumerate(self.paths, 1):
            try:
                transform_image_atomic(file_path, self.operation)
                successful.append(file_path)
            except Exception as error:
                errors[file_path] = str(error)
            self.progress.emit(position, total)
        self.result_ready.emit(successful, errors)


class BatchRotateDialog(QDialog):
    def __init__(self, paths, initial_operation="right", parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.successful_paths = []
        self.errors = {}
        self.worker = None
        self.setWindowTitle("Batch Rotate / Flip")
        self.resize(420, 190)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(self.paths)} selected images will be overwritten."))

        form = QFormLayout()
        self.operation_combo = QComboBox()
        for label, value in ROTATE_OPERATIONS:
            self.operation_combo.addItem(label, value)
        initial_index = self.operation_combo.findData(initial_operation)
        if initial_index >= 0:
            self.operation_combo.setCurrentIndex(initial_index)
        form.addRow("Operation:", self.operation_combo)
        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.execute_button = QPushButton("Execute && Save")
        self.execute_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.execute_button.clicked.connect(self.start_operation)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.execute_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def start_operation(self):
        self.execute_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.operation_combo.setEnabled(False)
        self.progress_bar.setRange(0, len(self.paths))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.worker = BatchRotateWorker(
            self.paths,
            self.operation_combo.currentData(),
            self,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.result_ready.connect(self.on_finished)
        self.worker.start(QThread.Priority.LowPriority)

    def on_progress(self, current, total):
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processed {current} / {total}")

    def on_finished(self, successful, errors):
        if self.worker is not None:
            self.worker.wait()
        self.worker = None
        self.successful_paths = successful
        self.errors = errors
        if errors:
            examples = [
                f"{os.path.basename(path)}: {message}"
                for path, message in list(errors.items())[:5]
            ]
            QMessageBox.warning(
                self,
                "Batch Rotate / Flip",
                f"Changed {len(successful)} of {len(self.paths)} images.\n\n" + "\n".join(examples),
            )
        self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return
        super().reject()
