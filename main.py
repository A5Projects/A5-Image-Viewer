import os
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow
from ui.theme import apply_theme
from utils.file_ops import get_ui_theme

APP_NAME = "A5ImageViewer"
ICON_FILE = "A5ImageViewer.ico"

def resource_path(filename):
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def startup_path_from_arguments(arguments):
    for argument in arguments:
        if not argument:
            continue
        candidate = os.path.abspath(os.path.expanduser(argument.strip('"')))
        if os.path.exists(candidate):
            return candidate
    return None

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(resource_path(ICON_FILE)))
    
    # Optional: Set global app styling or use Fusion style
    app.setStyle("Fusion")
    apply_theme(get_ui_theme())
    
    startup_path = startup_path_from_arguments(sys.argv[1:])
    window = MainWindow(startup_path=startup_path)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
