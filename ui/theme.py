from PyQt6.QtCore import QTemporaryDir
from PyQt6.QtGui import QColor, QPalette, QPainter
from PyQt6.QtWidgets import QApplication, QStyle

from utils.file_ops import UI_THEME_NAMES as THEME_NAMES

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
LIGHT = {
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
    "oled_black": {
        **DARK,
        "surface": "#121212", "base": "#0a0a0a", "alternate": "#151515",
        "text": "#e6eaee", "muted": "#9aa4ad", "disabled": "#768089",
        "toolbar": "#181818", "header": "#1c2024", "status": "#0e0e0e",
        "button": "#24272b", "hover": "#32373d", "pressed": "#29577a",
        "border": "#3f4b54", "control_border": "#52616d", "hover_border": "#758c9e",
        "field_border": "#485661", "focus": "#6cb3e8",
        "scroll": "#556572", "scroll_border": "#7f93a3", "scroll_hover": "#6d8394",
        "scroll_pressed": "#849eb3", "divider": "#47545e", "edge": "#5e6d78",
        "edge_shadow": "#1b2024", "split_hover": "#5c7487",
        "selection": "#256ec2", "selection_inactive": "#2b4b6e",
        "thumb_border": "#a8d5ff", "thumb_border_inactive": "#78b0e0",
        "check": "#1d2125", "check_border": "#8b9aa6", "check_hover": "#293036",
        "accent": "#2c93de", "accent_border": "#86cbff", "accent_hover": "#52b0f2",
        "track": "#383d42", "track_border": "#545c63", "track_empty": "#2b2f33",
        "error": "#ff7878", "tooltip": "#1f2428",
    },
    "midnight_slate": {
        **DARK,
        "surface": "#242a34", "base": "#1a1f27", "alternate": "#212731",
        "text": "#e3eaf2", "muted": "#9ca8b8", "disabled": "#7d8a9c",
        "toolbar": "#2b323f", "header": "#303947", "status": "#1e242d",
        "button": "#394354", "hover": "#48556a", "pressed": "#35638c",
        "border": "#4e5d73", "control_border": "#60728c", "hover_border": "#7e95b5",
        "field_border": "#566780", "focus": "#7db9e8",
        "scroll": "#5f738f", "scroll_border": "#8aa1bf", "scroll_hover": "#768eae",
        "scroll_pressed": "#8ea7c7", "divider": "#586982", "edge": "#6e819c",
        "edge_shadow": "#262f3b", "split_hover": "#6a82a3",
        "selection": "#2e72bd", "selection_inactive": "#38587a",
        "thumb_border": "#b2dcff", "thumb_border_inactive": "#88b9e6",
        "check": "#2c3542", "check_border": "#96a8bf", "check_hover": "#394557",
        "accent": "#3896e0", "accent_border": "#96d2ff", "accent_hover": "#5fb1f0",
        "track": "#4b5769", "track_border": "#69788f", "track_empty": "#3c4654",
        "error": "#ff7b82", "tooltip": "#2e3745",
    },
    "warm_charcoal": {
        **DARK,
        "surface": "#2b2623", "base": "#1e1a17", "alternate": "#26211e",
        "text": "#ede5dc", "muted": "#b2a599", "disabled": "#908479",
        "toolbar": "#332d29", "header": "#3a332e", "status": "#241f1c",
        "button": "#473f39", "hover": "#594f47", "pressed": "#7a5228",
        "border": "#665a50", "control_border": "#7a6c60", "hover_border": "#9c8a79",
        "field_border": "#6e6156", "focus": "#d9a05b",
        "scroll": "#7d6e61", "scroll_border": "#a89687", "scroll_hover": "#968475",
        "scroll_pressed": "#ab9888", "divider": "#6e6156", "edge": "#87786b",
        "edge_shadow": "#2e2824", "split_hover": "#8a7665",
        "selection": "#9e621c", "selection_inactive": "#6b4f32",
        "thumb_border": "#ffd599", "thumb_border_inactive": "#d9b17c",
        "check": "#38312c", "check_border": "#b0a092", "check_hover": "#473e38",
        "accent": "#c9822c", "accent_border": "#ffd094", "accent_hover": "#de9a45",
        "track": "#594f47", "track_border": "#75685d", "track_empty": "#473f39",
        "error": "#ff8278", "tooltip": "#3a332d",
    },
    "forest": {
        **DARK,
        "surface": "#212b26", "base": "#171f1b", "alternate": "#1e2823",
        "text": "#e2ece6", "muted": "#9cb0a4", "disabled": "#7d9185",
        "toolbar": "#28342e", "header": "#2e3c35", "status": "#1b241f",
        "button": "#37473f", "hover": "#465a50", "pressed": "#2a694c",
        "border": "#4d6358", "control_border": "#5f7a6c", "hover_border": "#7da18e",
        "field_border": "#546b5f", "focus": "#6ec99d",
        "scroll": "#5d786a", "scroll_border": "#88a898", "scroll_hover": "#729483",
        "scroll_pressed": "#88ad9b", "divider": "#556e61", "edge": "#6a8778",
        "edge_shadow": "#222e28", "split_hover": "#678a78",
        "selection": "#277351", "selection_inactive": "#335947",
        "thumb_border": "#a3f0ca", "thumb_border_inactive": "#7ac7a1",
        "check": "#2a3831", "check_border": "#96b0a2", "check_hover": "#36473f",
        "accent": "#339467", "accent_border": "#94e6be", "accent_hover": "#4db383",
        "track": "#495c52", "track_border": "#667d71", "track_empty": "#3a4a42",
        "error": "#ff7f82", "tooltip": "#2c3a33",
    },
    "dusk_plum": {
        **DARK,
        "surface": "#282430", "base": "#1d1a24", "alternate": "#24202c",
        "text": "#eae6f2", "muted": "#aba3bd", "disabled": "#8c849e",
        "toolbar": "#302b3a", "header": "#383245", "status": "#221e29",
        "button": "#443d54", "hover": "#554c69", "pressed": "#59428a",
        "border": "#5e5573", "control_border": "#72688c", "hover_border": "#9488b5",
        "field_border": "#665c7d", "focus": "#b098eb",
        "scroll": "#72678c", "scroll_border": "#9e92ba", "scroll_hover": "#887ca6",
        "scroll_pressed": "#9f93bf", "divider": "#685e80", "edge": "#80749c",
        "edge_shadow": "#2a2536", "split_hover": "#7e709e",
        "selection": "#6a4ba8", "selection_inactive": "#4c3e6b",
        "thumb_border": "#d6c4ff", "thumb_border_inactive": "#b09bd9",
        "check": "#342e42", "check_border": "#a89ec2", "check_hover": "#423b54",
        "accent": "#815ec4", "accent_border": "#d0bdff", "accent_hover": "#9c7cdb",
        "track": "#544c66", "track_border": "#706687", "track_empty": "#443d54",
        "error": "#ff8091", "tooltip": "#363042",
    },
    "light": LIGHT,
    "warm_paper": {
        **LIGHT,
        "surface": "#f1ece1", "base": "#faf7f0", "alternate": "#f2ece0",
        "text": "#29221c", "muted": "#5e5347", "disabled": "#7c7063",
        "toolbar": "#e7e0d2", "header": "#dfd7c7", "status": "#e7e0d2",
        "button": "#e6dfd0", "hover": "#e8d7be", "pressed": "#d9bf9c",
        "border": "#9c8f7d", "control_border": "#8c7e6c", "hover_border": "#78532a",
        "field_border": "#948673", "focus": "#8c4f18",
        "scroll": "#948573", "scroll_border": "#6e6050", "scroll_hover": "#7d6e5d",
        "scroll_pressed": "#635647", "divider": "#a19380", "edge": "#7a6c5a",
        "edge_shadow": "#d4cbbd", "split_hover": "#856e54",
        "selection": "#91521a", "selection_inactive": "#78624d",
        "thumb_border": "#8c4f18", "thumb_border_inactive": "#78624d",
        "check": "#faf7f0", "check_border": "#7a6c5a", "check_hover": "#f0e4d1",
        "accent": "#a66022", "accent_border": "#6e3d12", "accent_hover": "#bf7532",
        "track": "#ccc2b2", "track_border": "#8f8270", "track_empty": "#dbd2c3",
        "error": "#a82028", "tooltip": "#fff8e3",
    },
    "cool_mist": {
        **LIGHT,
        "surface": "#e8eef3", "base": "#f5f8fb", "alternate": "#eaf0f6",
        "text": "#1c252e", "muted": "#4c5c6b", "disabled": "#6c7c8c",
        "toolbar": "#dde5ec", "header": "#d4dfe8", "status": "#dde5ec",
        "button": "#dce4ec", "hover": "#c9dced", "pressed": "#b0cde6",
        "border": "#8496a6", "control_border": "#738799", "hover_border": "#3f688c",
        "field_border": "#7c90a3", "focus": "#1a619c",
        "scroll": "#788d9e", "scroll_border": "#52687a", "scroll_hover": "#617a8f",
        "scroll_pressed": "#44637d", "divider": "#899cad", "edge": "#5c7387",
        "edge_shadow": "#c5d1db", "split_hover": "#5a7a96",
        "selection": "#20639c", "selection_inactive": "#536f87",
        "thumb_border": "#1a619c", "thumb_border_inactive": "#4c6d8a",
        "check": "#f5f8fb", "check_border": "#5f778c", "check_hover": "#dfebf5",
        "accent": "#1e76bd", "accent_border": "#154f7d", "accent_hover": "#358dd4",
        "track": "#b8c8d6", "track_border": "#798fa3", "track_empty": "#cad6e0",
        "error": "#b02130", "tooltip": "#f2f7fc",
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
