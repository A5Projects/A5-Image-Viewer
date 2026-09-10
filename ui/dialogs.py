import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QGridLayout,
)
from utils.file_ops import get_recent_folders


WINDOWS_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED_FILENAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class RenameDialog(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.original_filename = filename
        self.new_filename = filename
        basename, extension = os.path.splitext(filename)

        self.setWindowTitle("Rename")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        fields = QGridLayout()
        fields.setColumnStretch(0, 1)

        fields.addWidget(QLabel("Name:"), 0, 0)
        fields.addWidget(QLabel("Extension:"), 0, 1)

        self.name_edit = QLineEdit(basename)
        self.extension_edit = QLineEdit(extension.lstrip("."))
        self.extension_edit.setMaximumWidth(110)
        fields.addWidget(self.name_edit, 1, 0)
        fields.addWidget(self.extension_edit, 1, 1)
        layout.addLayout(fields)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        rename_button = QPushButton("&Rename")
        rename_button.setDefault(True)
        rename_button.clicked.connect(self.accept_rename)
        cancel_button = QPushButton("&Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(rename_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def composed_filename(self):
        basename = self.name_edit.text().strip()
        extension = self.extension_edit.text().strip().lstrip(".")
        return f"{basename}.{extension}" if extension else basename

    @staticmethod
    def filename_error(filename):
        if not filename:
            return "The filename cannot be empty."
        if filename.endswith((" ", ".")):
            return "Windows filenames cannot end with a space or period."
        if any(
            character in WINDOWS_INVALID_FILENAME_CHARS or ord(character) < 32
            for character in filename
        ):
            return "The filename contains a character Windows does not allow."
        basename = filename.split(".", 1)[0].upper()
        if basename in WINDOWS_RESERVED_FILENAMES:
            return f"{basename} is a reserved Windows filename."
        return ""

    def accept_rename(self):
        filename = self.composed_filename()
        error = self.filename_error(filename)
        if error:
            QMessageBox.warning(self, "Rename", error)
            return
        self.new_filename = filename
        self.accept()

class CopyMoveDialog(QDialog):
    def __init__(self, parent=None, is_move=False):
        super().__init__(parent)
        self.is_move = is_move
        self.selected_folder = None
        self.setWindowTitle("Move To..." if is_move else "Copy To...")
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
        for folder in get_recent_folders():
            self.list_widget.addItem(folder)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            
        layout.addWidget(QLabel("Recent Folders:"))
        layout.addWidget(self.list_widget)

        layout.addWidget(QLabel("Destination:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Destination folder")
        current_item = self.list_widget.currentItem()
        if current_item:
            self.path_edit.setText(current_item.text())
        layout.addWidget(self.path_edit)
        
        btn_layout = QHBoxLayout()
        browse_btn = QPushButton("Browse...")
        browse_btn.setAutoDefault(False)
        browse_btn.clicked.connect(self.browse_folder)
        
        action_btn = QPushButton("Move" if is_move else "Copy")
        action_btn.setDefault(True)
        action_btn.clicked.connect(self.accept_action)
        
        self.list_widget.itemDoubleClicked.connect(self.accept_action)
        self.path_edit.returnPressed.connect(self.accept_action)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(browse_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(action_btn)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)

        self.list_widget.currentItemChanged.connect(self.on_recent_folder_selected)
        
    def browse_folder(self):
        start_folder = self.current_folder_text()
        folder = QFileDialog.getExistingDirectory(self, "Select Directory", start_folder)
        if folder:
            self.path_edit.setText(folder)
            
    def accept_action(self):
        folder = self.resolved_folder_text()
        if not folder:
            self.reject()
            return
        self.selected_folder = folder
        self.accept()

    def on_recent_folder_selected(self, current, previous):
        if current:
            self.path_edit.setText(current.text())

    def current_folder_text(self):
        text = self.path_edit.text().strip()
        if text:
            return text
        item = self.list_widget.currentItem()
        if item:
            return item.text()
        return ""

    def resolved_folder_text(self):
        text = os.path.expandvars(os.path.expanduser(self.current_folder_text()))
        if not text:
            return ""

        item = self.list_widget.currentItem()
        base_folder = item.text() if item else os.getcwd()
        drive, _ = os.path.splitdrive(text)
        if text[:1] in ("\\", "/") and not text.startswith(("\\\\", "//")) and not drive:
            return os.path.normpath(base_folder + text)

        if os.path.isabs(text):
            return os.path.normpath(text)

        return os.path.normpath(os.path.join(base_folder, text))
