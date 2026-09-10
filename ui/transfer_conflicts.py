import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QImageReader, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from utils.file_ops import add_recent_folder


AUTO_RENAME_PATTERN = re.compile(r"^(.*?)-ren\((\d+)\)$", re.IGNORECASE)
WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass
class TransferJob:
    job_id: int
    sources: list
    destination: str
    move_files: bool = False
    context: dict = field(default_factory=dict)
    create_destination: bool = False


@dataclass
class TransferItem:
    source: str
    target: str
    conflict: bool
    rename_target: str = ""
    source_size: int = 0
    source_modified: float = 0.0
    target_size: int = 0
    target_modified: float = 0.0


@dataclass
class TransferPlan:
    job: TransferJob
    items: list = field(default_factory=list)
    missing_sources: list = field(default_factory=list)
    error_code: str = ""
    error_text: str = ""


@dataclass
class ResolvedTransfer:
    source: str
    target: str
    replace: bool = False


class _PreflightSignals(QObject):
    ready = pyqtSignal(object)


def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def _safe_stat(path):
    try:
        stat = os.stat(path)
        return stat.st_size, stat.st_mtime
    except OSError:
        return 0, 0.0


def recommended_rename_target(source_path, destination_folder, reserved=None):
    reserved = reserved if reserved is not None else set()
    filename = os.path.basename(source_path)
    stem, extension = os.path.splitext(filename)
    match = AUTO_RENAME_PATTERN.match(stem)
    if match:
        root = match.group(1)
        number = int(match.group(2)) + 1
    else:
        root = stem
        number = 1

    while True:
        candidate = os.path.join(
            destination_folder,
            f"{root}-ren({number}){extension}",
        )
        key = _path_key(candidate)
        if key not in reserved and not os.path.exists(candidate):
            reserved.add(key)
            return candidate
        number += 1


def scan_transfer_job(job):
    try:
        if job.create_destination:
            os.makedirs(job.destination, exist_ok=True)

        if not os.path.isdir(job.destination):
            if os.path.exists(job.destination):
                return TransferPlan(
                    job,
                    error_code="invalid_destination",
                    error_text="The selected destination is not a folder.",
                )
            return TransferPlan(job, error_code="missing_destination")

        destination = os.path.abspath(job.destination)
        candidates = []
        missing_sources = []
        for source in job.sources:
            source = os.path.abspath(source)
            if not os.path.exists(source):
                missing_sources.append(source)
                continue
            if _path_key(os.path.dirname(source)) == _path_key(destination):
                continue
            target = os.path.join(destination, os.path.basename(source))
            candidates.append((source, target))

        reserved = {_path_key(target) for _, target in candidates}
        items = []
        for source, target in candidates:
            conflict = os.path.exists(target)
            rename_target = (
                recommended_rename_target(source, destination, reserved)
                if conflict else ""
            )
            source_size, source_modified = _safe_stat(source)
            target_size, target_modified = _safe_stat(target) if conflict else (0, 0.0)
            items.append(TransferItem(
                source=source,
                target=target,
                conflict=conflict,
                rename_target=rename_target,
                source_size=source_size,
                source_modified=source_modified,
                target_size=target_size,
                target_modified=target_modified,
            ))
        return TransferPlan(job, items=items, missing_sources=missing_sources)
    except Exception as error:
        return TransferPlan(
            job,
            error_code="scan_failed",
            error_text=str(error),
        )


def validate_filename(filename):
    if not filename:
        return "The filename is empty."
    if filename.endswith((" ", ".")):
        return "Windows filenames cannot end with a space or period."
    if any(character in WINDOWS_INVALID_CHARS or ord(character) < 32 for character in filename):
        return "The filename contains a character Windows does not allow."
    basename = filename.split(".", 1)[0].upper()
    if basename in WINDOWS_RESERVED_NAMES:
        return f"{basename} is a reserved Windows filename."
    return ""


def format_size(size):
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024.0
        unit += 1
    return f"{int(value)} {units[unit]}" if unit == 0 else f"{value:.2f} {units[unit]}"


def read_preview(path, maximum_size):
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(False)
        dimensions = reader.size()
        if dimensions.isValid() and not dimensions.isEmpty():
            reader.setScaledSize(dimensions.scaled(
                maximum_size,
                Qt.AspectRatioMode.KeepAspectRatio,
            ))
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        return pixmap, dimensions
    except Exception:
        return QPixmap(), QSize()


class TransferConflictDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.conflicts = [item for item in plan.items if item.conflict]
        self.index = 0
        self.decisions = {}
        self.reserved_targets = set()
        self.current_suggested_stem = ""

        self.setWindowTitle("File already exists")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)
        self.setMinimumSize(780, 560)
        self.resize(900, 650)

        main_layout = QVBoxLayout(self)
        self.progress_label = QLabel()
        main_layout.addWidget(self.progress_label)

        comparison_layout = QHBoxLayout()
        source_panel = self._build_file_panel("Incoming source")
        target_panel = self._build_file_panel("Existing destination")
        comparison_layout.addWidget(source_panel[0], 1)
        comparison_layout.addWidget(target_panel[0], 1)
        main_layout.addLayout(comparison_layout, 1)

        self.source_path_label, self.source_preview, self.source_details = source_panel[1:]
        self.target_path_label, self.target_preview, self.target_details = target_panel[1:]

        rename_layout = QHBoxLayout()
        rename_layout.addWidget(QLabel("New name:"))
        self.rename_edit = QLineEdit()
        self.rename_extension = QLabel()
        rename_layout.addWidget(self.rename_edit, 1)
        rename_layout.addWidget(self.rename_extension)
        main_layout.addLayout(rename_layout)

        button_layout = QHBoxLayout()
        self.replace_button = QPushButton("&Replace")
        self.replace_all_button = QPushButton("Replace &All")
        self.skip_button = QPushButton("&Skip")
        self.skip_all_button = QPushButton("Skip A&ll")
        self.rename_button = QPushButton("Re&name")
        self.rename_all_button = QPushButton("Rena&me All")
        self.cancel_button = QPushButton("&Cancel")

        self.replace_button.clicked.connect(lambda: self._choose("replace"))
        self.replace_all_button.clicked.connect(lambda: self._choose_all("replace"))
        self.skip_button.clicked.connect(lambda: self._choose("skip"))
        self.skip_all_button.clicked.connect(lambda: self._choose_all("skip"))
        self.rename_button.clicked.connect(lambda: self._choose("rename"))
        self.rename_all_button.clicked.connect(lambda: self._choose_all("rename"))
        self.cancel_button.clicked.connect(self.reject)

        for button in (
            self.replace_button, self.replace_all_button,
            self.skip_button, self.skip_all_button,
            self.rename_button, self.rename_all_button,
            self.cancel_button,
        ):
            button.setAutoDefault(False)
            button_layout.addWidget(button)
        self.skip_button.setAutoDefault(True)
        self.skip_button.setDefault(True)
        main_layout.addLayout(button_layout)

        self._load_current_conflict()

    @staticmethod
    def _build_file_panel(title):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        path_label = QLabel()
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview = QLabel("Preview unavailable")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(280, 220)
        preview.setProperty("imageCanvas", True)
        details = QLabel()
        details.setWordWrap(True)
        layout.addWidget(path_label)
        layout.addWidget(preview, 1)
        layout.addWidget(details)
        return group, path_label, preview, details

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.skip_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_file_panel(self, path, path_label, preview_label, details_label,
                        size, modified):
        path_label.setText(path)
        pixmap, dimensions = read_preview(path, QSize(340, 280))
        if pixmap.isNull():
            preview_label.setPixmap(QPixmap())
            preview_label.setText("Preview unavailable")
        else:
            preview_label.setText("")
            preview_label.setPixmap(pixmap)

        detail_lines = [format_size(size)]
        if dimensions.isValid() and not dimensions.isEmpty():
            detail_lines.append(f"{dimensions.width()} x {dimensions.height()}")
        if modified:
            detail_lines.append(datetime.fromtimestamp(modified).strftime("%Y-%m-%d  %H:%M:%S"))
        details_label.setText("   ".join(detail_lines))

    def _load_current_conflict(self):
        item = self.conflicts[self.index]
        self.progress_label.setText(
            f"Conflict {self.index + 1} of {len(self.conflicts)}"
        )
        self._set_file_panel(
            item.source, self.source_path_label, self.source_preview,
            self.source_details, item.source_size, item.source_modified,
        )
        self._set_file_panel(
            item.target, self.target_path_label, self.target_preview,
            self.target_details, item.target_size, item.target_modified,
        )
        suggested_name = os.path.basename(item.rename_target)
        suggested_stem, extension = os.path.splitext(suggested_name)
        self.current_suggested_stem = suggested_stem
        self.rename_edit.setText(suggested_stem)
        self.rename_extension.setText(extension)

    def _rename_target_for_current(self):
        item = self.conflicts[self.index]
        stem = self.rename_edit.text().strip()
        extension = os.path.splitext(item.source)[1]
        filename = f"{stem}{extension}"
        error = validate_filename(filename)
        if error:
            QMessageBox.warning(self, "Rename", error)
            return ""
        target = os.path.join(self.plan.job.destination, filename)
        key = _path_key(target)
        if key in self.reserved_targets or os.path.exists(target):
            if stem == self.current_suggested_stem:
                target = recommended_rename_target(
                    item.source,
                    self.plan.job.destination,
                    self.reserved_targets,
                )
            else:
                QMessageBox.warning(self, "Rename", "A file with that name already exists.")
                return ""
        else:
            self.reserved_targets.add(key)
        return target

    def _automatic_rename_target(self, item):
        target = item.rename_target
        key = _path_key(target)
        if key in self.reserved_targets or os.path.exists(target):
            return recommended_rename_target(
                item.source,
                self.plan.job.destination,
                self.reserved_targets,
            )
        self.reserved_targets.add(key)
        return target

    def _choose(self, action):
        item = self.conflicts[self.index]
        target = item.target
        if action == "rename":
            target = self._rename_target_for_current()
            if not target:
                return
        self.decisions[item.source] = (action, target)
        self.index += 1
        if self.index >= len(self.conflicts):
            self.accept()
        else:
            self._load_current_conflict()
            self.skip_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _choose_all(self, action):
        for offset, item in enumerate(self.conflicts[self.index:]):
            target = item.target
            if action == "rename":
                if offset == 0:
                    target = self._rename_target_for_current()
                    if not target:
                        return
                else:
                    target = self._automatic_rename_target(item)
            self.decisions[item.source] = (action, target)
        self.accept()

    def resolved_transfers(self):
        resolved = []
        for item in self.plan.items:
            if not item.conflict:
                resolved.append(ResolvedTransfer(item.source, item.target, False))
                continue
            action, target = self.decisions.get(item.source, ("skip", item.target))
            if action == "skip":
                continue
            resolved.append(ResolvedTransfer(
                item.source,
                target,
                replace=action == "replace",
            ))
        return resolved

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if self.rename_edit.hasFocus():
            super().keyPressEvent(event)
            return
        modifiers = event.modifiers()
        if not (
            modifiers & (
                Qt.KeyboardModifier.ControlModifier |
                Qt.KeyboardModifier.AltModifier |
                Qt.KeyboardModifier.ShiftModifier
            )
        ):
            actions = {
                "r": self.replace_button.click,
                "a": self.replace_all_button.click,
                "s": self.skip_button.click,
                "l": self.skip_all_button.click,
                "n": self.rename_button.click,
                "m": self.rename_all_button.click,
                "c": self.cancel_button.click,
            }
            action = actions.get(event.text().lower())
            if action is not None:
                action()
                event.accept()
                return
        super().keyPressEvent(event)


class TransferCoordinator(QObject):
    job_finished = pyqtSignal(object, object)
    pending_changed = pyqtSignal(int)

    def __init__(self, owner_provider, execute_callback, parent=None, max_scans=2):
        super().__init__(parent)
        self.owner_provider = owner_provider
        self.execute_callback = execute_callback
        self.max_scans = max(1, int(max_scans))
        self.next_job_id = 1
        self.pending_jobs = deque()
        self.ready_plans = deque()
        self.active_scans = 0
        self.resolving = False
        self.stopping = False
        self.signals = _PreflightSignals(self)
        self.signals.ready.connect(self._on_scan_ready)

    def enqueue(self, sources, destination, move_files=False, context=None):
        job = TransferJob(
            job_id=self.next_job_id,
            sources=[os.path.abspath(path) for path in sources if path],
            destination=os.path.abspath(destination),
            move_files=bool(move_files),
            context=dict(context or {}),
        )
        self.next_job_id += 1
        self.pending_jobs.append(job)
        self._start_pending_scans()
        self._emit_pending_count()
        return job.job_id

    def shutdown(self):
        self.stopping = True
        self.pending_jobs.clear()
        self.ready_plans.clear()

    def _emit_pending_count(self):
        self.pending_changed.emit(
            self.active_scans + len(self.pending_jobs) + len(self.ready_plans)
        )

    def _start_pending_scans(self):
        while (
            not self.stopping and
            self.pending_jobs and
            self.active_scans < self.max_scans
        ):
            job = self.pending_jobs.popleft()
            self.active_scans += 1
            thread = threading.Thread(
                target=self._scan_in_background,
                args=(job,),
                name=f"transfer-preflight-{job.job_id}",
                daemon=True,
            )
            thread.start()

    def _scan_in_background(self, job):
        plan = scan_transfer_job(job)
        try:
            self.signals.ready.emit(plan)
        except RuntimeError:
            pass

    def _on_scan_ready(self, plan):
        self.active_scans = max(0, self.active_scans - 1)
        if self.stopping:
            return
        self.ready_plans.append(plan)
        self._start_pending_scans()
        self._emit_pending_count()
        self._drain_ready_plans()

    def _owner(self):
        owner = self.owner_provider()
        return owner if isinstance(owner, QWidget) else None

    def _drain_ready_plans(self):
        if self.resolving or self.stopping or not self.ready_plans:
            return
        self.resolving = True
        plan = self.ready_plans.popleft()
        try:
            try:
                self._process_plan(plan)
            except Exception as error:
                QMessageBox.warning(
                    self._owner(),
                    "File Transfer",
                    f"The queued transfer failed:\n\n{error}",
                )
                self.job_finished.emit(
                    plan.job,
                    {"failed": list(plan.job.sources)},
                )
        finally:
            self.resolving = False
            self._emit_pending_count()
            QTimer.singleShot(0, self._drain_ready_plans)

    def _process_plan(self, plan):
        owner = self._owner()
        if plan.error_code == "missing_destination":
            reply = QMessageBox.question(
                owner,
                "Create Folder?",
                f"The destination folder does not exist:\n\n{plan.job.destination}\n\nCreate it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                plan.job.create_destination = True
                self.pending_jobs.appendleft(plan.job)
                self._start_pending_scans()
            else:
                self.job_finished.emit(plan.job, {"cancelled": True})
            return

        if plan.error_code:
            QMessageBox.warning(
                owner,
                "File Transfer",
                plan.error_text or "The destination could not be checked.",
            )
            self.job_finished.emit(plan.job, {"failed": list(plan.job.sources)})
            return

        try:
            add_recent_folder(plan.job.destination)
        except OSError:
            pass

        conflicts = [item for item in plan.items if item.conflict]
        if conflicts:
            dialog = TransferConflictDialog(plan, owner)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.job_finished.emit(plan.job, {"cancelled": True})
                return
            resolved = dialog.resolved_transfers()
        else:
            resolved = [
                ResolvedTransfer(item.source, item.target, False)
                for item in plan.items
            ]

        result = self.execute_callback(plan, resolved)
        self.job_finished.emit(plan.job, result or {})
