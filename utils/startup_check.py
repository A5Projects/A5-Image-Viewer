"""Developer-only packaged startup check with temporary files and configuration."""

import json
from pathlib import Path
import sys
import tempfile
import traceback


def _check_startup(folder):
    from PyQt6.QtCore import QTimer, qVersion
    from PyQt6.QtGui import QIcon, QImageReader
    from PyQt6.QtWidgets import QApplication
    from PIL import Image
    from utils import file_ops
    from utils.app_info import bundled_file
    from ui.about_dialog import AboutDialog
    from ui.main_window import MainWindow
    from ui.theme import apply_theme

    # Exercise the Windows platform plugin without showing any windows.
    platform = "windows" if sys.platform == "win32" else "offscreen"
    app = QApplication(["A5 startup check", "-platform", platform])
    app.setStyle("Fusion")
    previous_config = file_ops.CONFIG_FILE
    file_ops.CONFIG_FILE = str(folder / "config.json")
    window = None
    try:
        file_ops.set_startup_behavior("empty")
        apply_theme("dark")
        window = MainWindow()
        window.winId()
        if window.grab().isNull():
            raise RuntimeError("The browser could not render.")
        if QIcon(str(bundled_file("A5ImageViewer.ico"))).isNull():
            raise RuntimeError("The application icon is missing.")
        about = AboutDialog(window)
        if "GNU GENERAL PUBLIC LICENSE" not in about.license_browser.toPlainText():
            raise RuntimeError("The bundled license is missing.")
        if "# Changelog" not in bundled_file("CHANGELOG.md").read_text(encoding="utf-8"):
            raise RuntimeError("The bundled changelog is missing.")
        about.close()
        for extension in ("png", "jpg"):
            image_path = folder / f"sample.{extension}"
            Image.new("RGB", (32, 24), "red").save(image_path)
            reader = QImageReader(str(image_path))
            image = reader.read()
            if image.isNull() or image.width() != 32 or image.height() != 24:
                raise RuntimeError(f"{extension} decoding failed: {reader.errorString()}")
            del reader
        QTimer.singleShot(100, app.quit)
        app.exec()
        return {"qt_version": qVersion(), "platform": app.platformName()}
    finally:
        if window is not None:
            window.thumbnail_view.shutdown()
            window.crop_prefetch_service.shutdown()
            window.transfer_coordinator.shutdown()
            window.close()
        app.processEvents()
        file_ops.CONFIG_FILE = previous_config


def run_startup_check(report_path):
    report = {"ok": False}
    try:
        with tempfile.TemporaryDirectory(prefix="a5-startup-") as folder:
            report.update(_check_startup(Path(folder)))
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
