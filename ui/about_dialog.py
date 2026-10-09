from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from utils.app_info import (
    APP_NAME, APP_VERSION, RELEASE_DATE, GITHUB_URL, bundled_file, read_bundled_text,
)
from utils.file_ops import get_disable_f1_shortcut, set_disable_f1_shortcut


SHORTCUTS = {
    "Browser": [
        ("F1", "About, shortcuts, license, and changelog"),
        ("Ctrl+Shift+N", "Open the current folder in a new instance"),
        ("Enter / double-click", "Open the selected image, folder, or associated file"),
        ("C / M", "Copy To / Move To"),
        ("X / A", "Open Crop Board / Adjust Colors & Size"),
        ("F2", "Rename"),
        ("F3 / F4", "Open in associated application / associated editor"),
        ("F5", "Refresh folder"),
        ("Ctrl+C / Ctrl+X / Ctrl+V", "Copy / cut / paste files (text fields use normal text shortcuts)"),
        ("Ctrl+A", "Select all thumbnails when the thumbnail view has focus"),
        ("Delete / Shift+Delete", "Recycle / permanently delete selected files or folders"),
        ("Backspace", "Parent folder (thumbnail view or directory tree)"),
        ("Alt+Left / Alt+Right", "Previous / next folder in browsing history"),
        ("Alt+letter / Alt+0–9", "Next visible file or folder starting with that character; repeats cycle and wrap"),
        ("Shift+letter", "Alternative filename navigation in the thumbnail browser"),
        ("L / R", "Rotate left / right by 90°"),
        ("H / V", "Flip horizontally / vertically"),
        ("Ctrl+mouse wheel", "Zoom the image preview"),
    ],
    "Image viewer (fullscreen / windowed)": [
        ("F1 / F11", "About / switch fullscreen and windowed modes"),
        ("Escape", "Close and return to the image where viewing started"),
        ("Enter", "Close and select the displayed image in the browser"),
        ("Backspace", "Show the displayed image in the browser without closing"),
        ("Space / PgDown / N / wheel down", "Next image"),
        ("PgUp / P / wheel up", "Previous image"),
        ("Ctrl+Home / Ctrl+End", "First / last image"),
        ("Pause", "Start / stop slideshow"),
        ("Ctrl+H", "Show / hide image information"),
        ("+ / = / − / Ctrl+mouse wheel", "Zoom in / out"),
        ("* / / / 5 (including keypad)", "Fit / actual size / 200%"),
        ("Arrow keys / right-drag", "Pan"),
        ("Left-drag / Ctrl+A", "Select pixels / select the whole image"),
        ("Ctrl+C", "Copy selected pixels, or the whole image"),
        ("Ctrl+X / Ctrl+V", "Cut the image file / paste files into the browser folder"),
        ("C / M", "Copy To / Move To"),
        ("F2 / F3 / F4", "Rename / associated application / associated editor"),
        ("Delete / Shift+Delete", "Recycle / permanently delete the displayed file"),
        ("X / A", "Crop Board / Adjust Colors & Size"),
        ("L / R / H / V", "Rotate left / right; flip horizontally / vertically"),
    ],
    "Crop Board": [
        ("F1", "About and shortcuts"),
        ("PgDown / N / wheel down", "Next image"),
        ("PgUp / P / wheel up", "Previous image"),
        ("+ / = / − / Ctrl+mouse wheel", "Zoom in / out"),
        ("* / /", "Fit / actual size"),
        ("Right-drag / left-drag", "Pan / select crop rectangle"),
        ("Ctrl+A", "Create a full-image crop selection"),
        ("C", "Crop in memory"),
        ("F", "Save crop with a unique _crop name: choose a remembered folder, or save beside the image with Auto"),
        ("S", "Save image"),
        ("X", "Crop, save, and move to the next image"),
        ("Ctrl+Z / Ctrl+R", "Undo / reset"),
        ("L / R / H / V", "Rotate left / right; flip horizontally / vertically"),
        ("Escape", "Close Crop Board"),
    ],
    "Adjust Colors & Size": [
        ("F1", "About and shortcuts"),
        ("PgDown / N", "Next image"),
        ("PgUp / P", "Previous image"),
        ("+ / − / Ctrl+mouse wheel", "Zoom preview in / out"),
        ("* / /", "Fit / actual preview size (preview is limited to 1200 × 1200)"),
        ("O", "Save / overwrite adjusted image"),
        ("F", "Save adjusted image to a file"),
        ("R", "Reset adjustments"),
        ("Escape", "Close Adjust"),
    ],
    "Settings and dialogs": [
        ("F1 (Settings)", "About and shortcuts"),
        ("Tab / Shift+Tab", "Move between controls"),
        ("Space", "Activate a focused button or checkbox"),
        ("Escape", "Cancel / close a dialog; unavailable during batch conversion"),
        ("Enter (Adjust)", "Does not save; use O or the Save button"),
    ],
}


class AboutDialog(QDialog):
    def __init__(self, parent=None, section="Browser"):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setWindowIcon(QIcon(str(bundled_file("A5ImageViewer.ico"))))
        self.resize(730, 560)
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(48, 48))
        heading.addWidget(icon)
        details = QLabel(
            f"<b>{APP_NAME} {APP_VERSION}</b><br>Update: {RELEASE_DATE}<br>"
            f'<a href="{GITHUB_URL}">GitHub project</a> · '
            f'<a href="{GITHUB_URL}/releases">Releases</a> · GNU GPL version 3'
        )
        details.setOpenExternalLinks(True)
        heading.addWidget(details, 1)
        layout.addLayout(heading)
        self.tabs = QTabWidget()
        shortcut_page = QWidget()
        shortcut_layout = QVBoxLayout(shortcut_page)
        self.section_combo = QComboBox()
        self.section_combo.addItems(SHORTCUTS)
        self.shortcut_browser = QTextBrowser()
        shortcut_layout.addWidget(self.section_combo)
        shortcut_layout.addWidget(self.shortcut_browser)
        self.section_combo.currentTextChanged.connect(self.show_shortcuts)
        self.section_combo.setCurrentText(section)
        self.show_shortcuts(self.section_combo.currentText())
        self.tabs.addTab(shortcut_page, "Shortcuts")
        self.changelog_browser = QTextBrowser()
        self.changelog_browser.setOpenExternalLinks(True)
        self.changelog_browser.setMarkdown(read_bundled_text("CHANGELOG.md"))
        self.tabs.addTab(self.changelog_browser, "Changelog")
        self.license_browser = QTextBrowser()
        self.license_browser.setPlainText(
            "Copyright (C) 2026 A5Projects.\n"
            "Licensed under the GNU General Public License version 3.\n\n"
            + read_bundled_text("LICENSE")
        )
        self.tabs.addTab(self.license_browser, "License")
        layout.addWidget(self.tabs)
        footer = QHBoxLayout()
        self.disable_f1_check = QCheckBox("Disable F1 shortcut")
        self.disable_f1_check.setChecked(get_disable_f1_shortcut())
        self.disable_f1_check.setToolTip("About remains available from Settings.")
        self.disable_f1_check.toggled.connect(self.change_f1_preference)
        footer.addWidget(self.disable_f1_check)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def change_f1_preference(self, disabled):
        set_disable_f1_shortcut(disabled)
        for window in QApplication.topLevelWidgets():
            for shortcut in window.findChildren(QShortcut, "aboutShortcut"):
                shortcut.setEnabled(not disabled)

    def show_shortcuts(self, section):
        rows = "".join(
            f'<tr><td valign="top"><b>{escape(keys)}</b></td><td>{escape(action)}</td></tr>'
            for keys, action in SHORTCUTS[section]
        )
        self.shortcut_browser.setHtml(
            f"<h3>{escape(section)}</h3><table cellspacing='10'>{rows}</table>"
            "<p>Single-letter shortcuts apply outside text-entry controls. "
            "Mouse-wheel navigation applies over the image canvas.</p>"
        )


def show_about(parent, section="Browser"):
    AboutDialog(parent, section).exec()


def install_about_shortcut(window, section):
    shortcut = QShortcut(QKeySequence("F1"), window)
    shortcut.setObjectName("aboutShortcut")
    shortcut.setEnabled(not get_disable_f1_shortcut())
    shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
    shortcut.activated.connect(lambda: show_about(window, section))
    return shortcut
