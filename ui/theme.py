from PyQt6.QtCore import QTemporaryDir
from PyQt6.QtGui import QColor, QPalette, QPainter
from PyQt6.QtWidgets import QApplication, QStyle


THEME_NAMES = (("dark", "Dark"), ("medium_dark", "Medium Dark"), ("light", "Light"))

DARK = {
    "surface": "#2b2b2b", "base": "#1e1e1e", "alternate": "#272727",
    "text": "#e0e0e0", "muted": "#a0a5a9", "disabled": "#81888d",
    "toolbar": "#333333", "header": "#33383c", "status": "#252525",
    "button": "#444444", "hover": "#555555", "pressed": "#3f6f8f",
    "border": "#53616b", "control_border": "#667680", "hover_border": "#8298a6",
    "field_border": "#596974", "focus": "#79a9c8",
    "scroll": "#687985", "scroll_border": "#8fa2ae", "scroll_hover": "#8198a7",
    "scroll_pressed": "#91aaba", "divider": "#60717d", "edge": "#74838d",
    "edge_shadow": "#30373c", "split_hover": "#718898",
    "selection": "#2f78d0", "selection_text": "#ffffff",
    "selection_inactive": "#355a80", "thumb_border": "#b6dcff",
    "thumb_border_inactive": "#8fc7ff",
    "check": "#353a3e", "check_border": "#9ba8b2", "check_hover": "#41484d",
    "accent": "#269be8", "accent_border": "#8bd2ff", "accent_hover": "#55b8f4",
    "track": "#565656", "track_border": "#707070", "track_empty": "#4a4a4a",
    "error": "#ff7777", "tooltip": "#363b3f",
}
THEMES = {
    "dark": DARK,
    "medium_dark": {
        **DARK,
        "surface": "#454545", "base": "#363636", "alternate": "#404040",
        "text": "#f2f2f2", "muted": "#bfc4c8", "disabled": "#a0a4a8",
        "toolbar": "#4c4c4c", "header": "#505458", "status": "#3d3d3d",
        "button": "#5b5b5b", "hover": "#696969", "border": "#84919a",
        "control_border": "#929da5", "field_border": "#89959e",
        "scroll": "#9aa8b2", "scroll_border": "#c2ccd2", "scroll_hover": "#b0bec8",
        "scroll_pressed": "#cad8e2", "divider": "#9ba7af", "edge": "#aebac2",
        "edge_shadow": "#3d4348", "check": "#494e52", "check_border": "#c0c9cf",
        "track": "#858585", "track_border": "#a4a4a4", "track_empty": "#686868",
        "tooltip": "#505458",
    },
    "light": {
        **DARK,
        "surface": "#f2f2f2", "base": "#ffffff", "alternate": "#f0f3f5",
        "text": "#202428", "muted": "#545e66", "disabled": "#737b82",
        "toolbar": "#e7e9eb", "header": "#e0e5e9", "status": "#e7e9eb",
        "button": "#e4e8eb", "hover": "#d4e4f0", "pressed": "#b9d5e9",
        "border": "#8997a1", "control_border": "#798b98", "hover_border": "#476e8c",
        "field_border": "#81929e", "focus": "#166da8",
        "scroll": "#7c8d9a", "scroll_border": "#566b7a", "scroll_hover": "#647d8f",
        "scroll_pressed": "#45677f", "divider": "#8e9fab", "edge": "#607787",
        "edge_shadow": "#cad2d8", "split_hover": "#607f95",
        "selection": "#216eae", "selection_inactive": "#59758c",
        "thumb_border": "#166da8", "thumb_border_inactive": "#4d708c",
        "check": "#ffffff", "check_border": "#657b8a", "check_hover": "#e4eff7",
        "accent": "#1684cc", "accent_border": "#165b89", "accent_hover": "#329bdf",
        "track": "#bdc9d2", "track_border": "#8093a1", "track_empty": "#ced6dc",
        "error": "#b52130", "tooltip": "#ffffeb",
    },
}


def theme_colors(name=None):
    app = QApplication.instance()
    if name is None and app is not None:
        name = app.property("ui_theme")
    return THEMES.get(name, DARK)


def theme_palette(colors):
    palette = QPalette()
    roles = {
        "Window": "surface", "WindowText": "text", "Base": "base",
        "AlternateBase": "alternate", "Text": "text", "Button": "button",
        "ButtonText": "text", "ToolTipBase": "tooltip", "ToolTipText": "text",
        "Highlight": "selection", "HighlightedText": "selection_text",
        "PlaceholderText": "muted", "Light": "edge", "Midlight": "hover",
        "Mid": "border", "Dark": "edge_shadow", "Shadow": "edge_shadow",
        "Link": "focus", "LinkVisited": "focus", "BrightText": "selection_text",
    }
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[token]))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight,
                     QColor(colors["selection_inactive"]))
    for role in ("WindowText", "Text", "ButtonText", "PlaceholderText"):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                         QColor(colors["disabled"]))
    return palette


def theme_stylesheet(c):
    return """
        QMainWindow, QDialog { background-color: %(surface)s; color: %(text)s; }
        QToolTip { background-color: %(tooltip)s; color: %(text)s; border: 1px solid %(border)s; }
        QTreeView, QListView, QTableView {
            background-color: %(base)s; alternate-background-color: %(alternate)s;
            color: %(text)s; border: 1px solid %(border)s;
        }
        QTreeView::item:hover, QListWidget[folderShortcuts="true"]::item:hover {
            background-color: %(hover)s;
        }
        QTreeView::item:selected, QListWidget[folderShortcuts="true"]::item:selected {
            background-color: %(selection)s; color: %(selection_text)s;
        }
        QTreeView::item:selected:!active, QListWidget[folderShortcuts="true"]::item:selected:!active {
            background-color: %(selection_inactive)s; color: %(selection_text)s;
        }
        QListWidget[folderShortcuts="true"]::item { padding: 0 4px; }
        QGraphicsView { background-color: #1e1e1e; border: 1px solid %(border)s; }
        QDialog#fullscreenViewer { background-color: black; }
        QGraphicsView#fullscreenImageView { background-color: black; border: none; }
        QLabel[imageCanvas="true"] { background-color: #181818; color: #e0e0e0; border: 1px solid %(border)s; }
        QWidget#folderShortcutsPanel { background-color: %(base)s; }
        QFrame#favoritesDivider { background-color: %(border)s; border: none; }
        QToolBar { background-color: %(toolbar)s; border-bottom: 1px solid %(border)s; }
        QToolBar::separator { background-color: %(divider)s; width: 1px; height: 1px; margin: 4px; }
        QStatusBar { background-color: %(status)s; color: %(text)s; border-top: 1px solid %(border)s; font-size: 10px; }
        QPushButton { background-color: %(button)s; color: %(text)s; border: 1px solid %(control_border)s; padding: 5px; border-radius: 3px; }
        QPushButton:hover { background-color: %(hover)s; border-color: %(hover_border)s; }
        QPushButton:pressed, QToolButton:pressed { background-color: %(pressed)s; border-color: %(focus)s; }
        QPushButton:default, QPushButton:focus, QToolButton:focus { border-color: %(focus)s; }
        QPushButton:disabled, QToolButton:disabled { color: %(disabled)s; }
        QToolButton { color: %(text)s; }
        QToolButton:hover { background-color: %(hover)s; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: %(surface)s; color: %(text)s; border: 1px solid %(field_border)s;
            selection-background-color: %(selection)s; selection-color: %(selection_text)s;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: %(focus)s; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: %(disabled)s; }
        QHeaderView::section { background-color: %(header)s; color: %(text)s; border: 1px solid %(border)s; }
        QGroupBox { border: 1px solid %(border)s; margin-top: 9px; }
        QGroupBox::title { subcontrol-origin: margin; left: 6px; padding: 0 3px; }
        QMenu { background-color: %(toolbar)s; color: %(text)s; border: 1px solid %(border)s; }
        QMenu::item:selected { background-color: %(selection)s; color: %(selection_text)s; }
        QMenu::item:disabled { color: %(disabled)s; }
        QMenu::separator { height: 1px; background-color: %(border)s; margin: 3px 6px; }
        QSplitter::handle { background-color: %(border)s; }
        QSplitter::handle:horizontal { border-left: 1px solid %(edge)s; border-right: 1px solid %(edge_shadow)s; }
        QSplitter::handle:vertical { border-top: 1px solid %(edge)s; border-bottom: 1px solid %(edge_shadow)s; }
        QSplitter::handle:hover { background-color: %(split_hover)s; }
        QScrollBar:vertical { background-color: %(base)s; width: 14px; margin: 14px 0; }
        QScrollBar:horizontal { background-color: %(base)s; height: 14px; margin: 0 14px; }
        QScrollBar::add-page, QScrollBar::sub-page { background-color: %(base)s; }
        QScrollBar::sub-line:vertical {
            background-color: %(button)s; border: 1px solid %(border)s;
            height: 12px; subcontrol-position: top; subcontrol-origin: margin;
        }
        QScrollBar::add-line:vertical {
            background-color: %(button)s; border: 1px solid %(border)s;
            height: 12px; subcontrol-position: bottom; subcontrol-origin: margin;
        }
        QScrollBar::sub-line:horizontal {
            background-color: %(button)s; border: 1px solid %(border)s;
            width: 12px; subcontrol-position: left; subcontrol-origin: margin;
        }
        QScrollBar::add-line:horizontal {
            background-color: %(button)s; border: 1px solid %(border)s;
            width: 12px; subcontrol-position: right; subcontrol-origin: margin;
        }
        QScrollBar::sub-line:hover, QScrollBar::add-line:hover { background-color: %(hover)s; }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background-color: %(scroll)s; border: 1px solid %(scroll_border)s; border-radius: 2px;
        }
        QScrollBar::handle:vertical { min-height: 24px; }
        QScrollBar::handle:horizontal { min-width: 24px; }
        QScrollBar::handle:hover { background-color: %(scroll_hover)s; border-color: %(edge)s; }
        QScrollBar::handle:pressed { background-color: %(scroll_pressed)s; }
        QCheckBox { spacing: 6px; }
        QCheckBox::indicator { width: 15px; height: 15px; border-radius: 2px; }
        QCheckBox::indicator:unchecked { background-color: %(check)s; border: 2px solid %(check_border)s; }
        QCheckBox::indicator:unchecked:hover { background-color: %(check_hover)s; border-color: %(focus)s; }
        QCheckBox::indicator:checked { background-color: %(accent)s; border: 2px solid %(accent_border)s; }
        QCheckBox::indicator:checked:hover { background-color: %(accent_hover)s; }
        QCheckBox::indicator:disabled { background-color: %(surface)s; border-color: %(disabled)s; }
        QSlider::groove:horizontal { height: 5px; background: %(track)s; border: 1px solid %(track_border)s; }
        QSlider::sub-page:horizontal { background: %(selection)s; border: 1px solid %(accent_border)s; }
        QSlider::add-page:horizontal { background: %(track_empty)s; }
        QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: %(accent)s; border: 1px solid %(accent_border)s; border-radius: 3px; }
        QSlider::handle:horizontal:hover { background: %(accent_hover)s; }
        QSlider::handle:horizontal:disabled { background: %(disabled)s; }
        QWidget#driveBar { background-color: %(header)s; border: 1px solid %(border)s; }
        QWidget#driveBar QToolButton { padding: 0 1px; background-color: %(header)s; border: 1px solid transparent; }
        QWidget#driveBar QToolButton:hover { background-color: %(hover)s; border-color: %(hover_border)s; }
        QWidget#driveBar QToolButton:pressed, QWidget#driveBar QToolButton:checked {
            background-color: %(pressed)s; border-color: %(focus)s;
        }
        QPushButton[cropPressFeedback="true"], QToolButton[cropPressFeedback="true"] {
            background-color: %(pressed)s; border: 2px solid %(focus)s;
        }
        QLabel[error="true"], QCheckBox[destructive="true"] { color: %(error)s; }
    """ % c


def scrollbar_arrow_styles(app, name, colors):
    # Qt suppresses native arrows when scrollbar subcontrols are styled.
    # Keep four tiny, recolored Qt icons per theme in a process-local temp dir.
    if not hasattr(app, "_theme_icon_directory"):
        app._theme_icon_directory = QTemporaryDir()
    directory = app._theme_icon_directory.path()
    if not directory:
        return ""
    rules = []
    for direction in ("up", "down", "left", "right"):
        path = f"{directory}/{name}-{direction}.png"
        icon = app.style().standardIcon(
            getattr(QStyle.StandardPixmap, "SP_Arrow" + direction.title())
        )
        pixmap = icon.pixmap(16, 16)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(colors["text"]))
        painter.end()
        if pixmap.save(path):
            rules.append(
                f'QScrollBar::{direction}-arrow {{ image: url("{path}"); width: 8px; height: 8px; }}'
            )
    return "\n".join(rules)


def apply_theme(name):
    app = QApplication.instance()
    if app is None:
        return
    name = name if name in THEMES else "dark"
    if app.property("ui_theme") == name:
        return
    app.setProperty("ui_theme", name)
    colors = THEMES[name]
    app.setPalette(theme_palette(colors))
    app.setStyleSheet(theme_stylesheet(colors) + scrollbar_arrow_styles(app, name, colors))
