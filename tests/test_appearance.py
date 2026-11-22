import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPalette, QStandardItem
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from tests.qt_wait import wait_until
from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog
from ui.theme import THEME_NAMES, THEMES, apply_theme
from ui.thumbnail_view import ThumbnailView
from utils import file_ops


def _relative_luminance(hex_color):
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground, background):
    l1 = _relative_luminance(foreground)
    l2 = _relative_luminance(background)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.original_font = cls.app.font()
        if os.path.isfile("C:/Windows/Fonts/segoeui.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
            cls.app.setFont(QFont("Segoe UI", 10))

    @classmethod
    def tearDownClass(cls):
        cls.app.setFont(cls.original_font)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(
            file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json")
        )
        self.config_patch.start()
        file_ops.set_startup_behavior("empty")
        self.previous_theme = self.app.property("ui_theme") or "dark"
        apply_theme("dark")
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.thumbnail_view.shutdown()
            self.window.crop_prefetch_service.shutdown()
            self.window.close()
            self.window.deleteLater()
        self.app.processEvents()
        apply_theme(self.previous_theme)
        self.config_patch.stop()
        self.temp.cleanup()

    def make_window(self, favorite_count=0):
        config = file_ops.load_config()
        config["favorite_folders"] = [
            os.path.join(self.temp.name, f"Favorite {i:03d}")
            for i in range(favorite_count)
        ]
        file_ops.save_config(config)
        self.window = MainWindow()
        self.window.show()
        QTest.qWait(30)
        return self.window

    def test_favorites_scroll_in_two_columns_below_pinned_shortcuts(self):
        window = self.make_window(80)
        system = window.quick_access_list
        favorites = window.favorites_list
        self.assertEqual(
            favorites.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
        )
        for list_widget in (system, favorites):
            rects = [list_widget.visualItemRect(list_widget.item(i)) for i in range(4)]
            self.assertEqual(rects[0].top(), rects[1].top())
            self.assertGreater(rects[1].left(), rects[0].left())
            self.assertGreater(rects[2].top(), rects[0].top())
            self.assertEqual(rects[0].left(), rects[2].left())
            self.assertEqual(list_widget.horizontalScrollBar().maximum(), 0)

        pinned_rects = [system.visualItemRect(system.item(i)) for i in range(5)]
        self.assertTrue(all(system.viewport().rect().contains(r) for r in pinned_rects))
        self.assertGreater(favorites.verticalScrollBar().maximum(), 0)
        favorites.scrollToBottom()
        self.app.processEvents()
        self.assertEqual(system.verticalScrollBar().value(), 0)
        self.assertEqual(pinned_rects, [system.visualItemRect(system.item(i)) for i in range(5)])
        self.assertTrue(favorites.visualItemRect(favorites.item(79)).intersects(favorites.viewport().rect()))

        window.navigation_splitter.setSizes([0, 600])
        self.app.processEvents()
        self.assertGreaterEqual(favorites.height(), 2 * favorites.gridSize().height())
        self.assertTrue(all(system.viewport().rect().contains(r) for r in pinned_rects))

    def test_uneven_favorite_columns_do_not_reflow_with_scrollbar(self):
        window = self.make_window(7)
        favorites = window.favorites_list
        favorites.setFixedHeight(4 * favorites.gridSize().height() + 2 * favorites.frameWidth())
        QTest.qWait(30)

        initial_width = favorites.viewport().width()
        initial_grid = favorites.gridSize()
        initial_rects = [favorites.visualItemRect(favorites.item(i)) for i in range(7)]
        for _ in range(20):
            self.app.processEvents()
            favorites.update_cell_geometry()

        self.assertEqual(favorites.viewport().width(), initial_width)
        self.assertEqual(favorites.gridSize(), initial_grid)
        self.assertEqual(
            [favorites.visualItemRect(favorites.item(i)) for i in range(7)],
            initial_rects,
        )
        self.assertGreater(initial_rects[1].left(), initial_rects[0].left())
        self.assertEqual(initial_rects[6].left(), initial_rects[0].left())

    def test_favorites_reflow_on_resize_and_font_change_without_losing_paths(self):
        window = self.make_window(9)
        favorites = window.favorites_list
        original_paths = [favorites.item(i).data(Qt.ItemDataRole.UserRole) for i in range(9)]
        font = QFont(favorites.font())
        font.setPointSizeF(max(9, font.pointSizeF()) * 1.5)
        favorites.setFont(font)
        window.splitter_h.setSizes([460, 700])
        QTest.qWait(30)
        self.assertEqual(favorites.gridSize().width(), (favorites.viewport().width() - 1) // 2)
        self.assertGreaterEqual(favorites.gridSize().height(), favorites.fontMetrics().height())
        self.assertEqual(original_paths, [favorites.item(i).data(Qt.ItemDataRole.UserRole) for i in range(9)])
        self.assertEqual(favorites.item(0).toolTip(), original_paths[0])

    def test_theme_setting_persists_and_defaults_safely(self):
        self.assertEqual(len(THEMES), 10)
        self.assertEqual(set(THEMES), {name for name, _ in THEME_NAMES})
        self.assertEqual(set(THEMES), file_ops.VALID_UI_THEMES)
        self.assertEqual(file_ops.get_ui_theme(), "dark")
        for name in THEMES:
            file_ops.set_ui_theme(name)
            dialog = SettingsDialog()
            self.assertEqual(dialog.theme_combo.currentData(), name)
            dialog.deleteLater()
        config = file_ops.load_config()
        config["ui_theme"] = "old-or-unknown-theme"
        file_ops.save_config(config)
        self.assertEqual(file_ops.get_ui_theme(), "dark")

    def test_all_themes_meet_contrast_thresholds(self):
        legacy_themes = {"dark", "medium_dark", "light"}
        common_pairs = (
            ("text", "base", 7.0),
            ("text", "surface", 6.0),
            ("text", "button", 4.5),
            ("text", "toolbar", 5.0),
            ("text", "tooltip", 5.0),
            ("selection_text", "selection", 4.4),
            ("selection_text", "selection_inactive", 4.4),
            ("error", "surface", 3.5),
        )
        new_theme_aa_pairs = (
            ("selection_text", "selection", 4.5),
            ("selection_text", "selection_inactive", 4.5),
            ("error", "surface", 4.5),
        )
        for name, colors in THEMES.items():
            for fg, bg, minimum in common_pairs:
                with self.subTest(theme=name, fg=fg, bg=bg):
                    self.assertGreaterEqual(_contrast_ratio(colors[fg], colors[bg]), minimum)
            if name not in legacy_themes:
                for fg, bg, minimum in new_theme_aa_pairs:
                    with self.subTest(theme=name, fg=fg, bg=bg):
                        self.assertGreaterEqual(_contrast_ratio(colors[fg], colors[bg]), minimum)

    def test_thumbnail_selection_fill_follows_active_theme(self):
        view = ThumbnailView()
        self.addCleanup(view.close)
        self.addCleanup(view.shutdown)
        view.thumbnail_model.appendRow(QStandardItem())
        index = view.model().index(0, 0)

        def paint_center(theme_name):
            apply_theme(theme_name)
            canvas = QImage(120, 120, QImage.Format.Format_ARGB32_Premultiplied)
            canvas.fill(0)
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 120, 120)
            option.state = (
                QStyle.StateFlag.State_Enabled
                | QStyle.StateFlag.State_Selected
                | QStyle.StateFlag.State_Active
            )
            painter = QPainter(canvas)
            view.itemDelegate().paint(painter, option, index)
            painter.end()
            return QColor(canvas.pixel(60, 60))

        dark_fill = paint_center("dark")
        warm_fill = paint_center("warm_charcoal")
        forest_fill = paint_center("forest")
        self.assertGreater(dark_fill.blue(), dark_fill.red())
        self.assertGreater(warm_fill.red(), warm_fill.blue())
        self.assertGreater(forest_fill.green(), forest_fill.red())
        self.assertNotEqual(warm_fill.rgb(), dark_fill.rgb())

    def test_theme_only_settings_do_not_restart_workers_or_reload_thumbnails(self):
        window = self.make_window()
        paths = []
        for i in range(40):
            path = os.path.join(self.temp.name, f"image{i:02d}.png")
            Image.new("RGB", (8, 8), "red").save(path)
            paths.append(path)
        window.current_folder_path = self.temp.name
        view = window.thumbnail_view
        view.load_folder(self.temp.name, show_folders=False)
        wait_until(lambda: all(path in view.thumbnail_cache for path in paths))
        window.select_image_by_path(paths[25])
        wait_until(lambda: view.verticalScrollBar().value() > 0)
        view.set_background_activity_paused(True)
        model = view.model()
        cache = dict(view.thumbnail_cache)
        current = view.currentIndex()
        scroll = view.verticalScrollBar().value()
        preview = window.preview_viewer.pixmap_item.pixmap().cacheKey()
        self.assertTrue(cache)
        self.assertGreater(scroll, 0)
        cycle = [name for name in THEMES if name != "dark"] + ["dark"]
        with (
            patch.object(view, "load_folder") as load_folder,
            patch.object(window, "apply_resource_settings") as resources,
            patch.object(window, "load_prefetched_preview") as preview_load,
        ):
            for name in cycle:
                dialog = SettingsDialog(window)
                dialog.theme_changed.connect(apply_theme)
                dialog.resource_settings_changed.connect(window.apply_resource_settings)
                theme_spy = QSignalSpy(dialog.theme_changed)
                dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData(name))
                dialog.accept()
                QTest.qWait(20)
                self.assertEqual(len(theme_spy), 1)
                self.assertEqual(self.app.property("ui_theme"), name)
                self.assertIs(view.model(), model)
                self.assertEqual(dict(view.thumbnail_cache), cache)
                self.assertEqual(view.currentIndex(), current)
                self.assertEqual(view.verticalScrollBar().value(), scroll)
                self.assertEqual(window.preview_viewer.pixmap_item.pixmap().cacheKey(), preview)
                self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window).name(), THEMES[name]["surface"])
            resources.assert_not_called()
            load_folder.assert_not_called()
            preview_load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
