import os
import random
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QMenu, QApplication, QLabel, QGraphicsView
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QPixmap, QFontMetrics
from ui.image_viewer import ImageViewer
from ui.crop_board import ResizableRectItem
from utils.file_ops import (
    get_fullscreen_hud_visible, set_fullscreen_hud_visible,
    get_slideshow_mode, set_slideshow_mode as save_slideshow_mode,
)


class FullscreenImageViewer(ImageViewer):
    context_menu_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.selection_rect_item = None
        self.selection_start = None
        self.right_press_pos = None
        self.right_last_pos = None
        self.right_dragged = False

    def set_pixmap(self, pixmap):
        self.clear_selection()
        super().set_pixmap(pixmap)

    def clear_image(self):
        self.clear_selection()
        super().clear_image()

    def clear_selection(self):
        if self.selection_rect_item is not None:
            if self.selection_rect_item.scene() is self.scene:
                self.scene.removeItem(self.selection_rect_item)
            self.selection_rect_item = None
        self.selection_start = None

    def select_all(self):
        pixmap = self.pixmap_item.pixmap()
        if pixmap.isNull():
            return False
        self._ensure_selection()
        self.scene.clearSelection()
        self.selection_rect_item.setRect(self.pixmap_item.boundingRect())
        self.selection_rect_item.setSelected(True)
        self.selection_rect_item.update_handles_pos()
        return True

    def selected_pixmap(self):
        pixmap = self.pixmap_item.pixmap()
        if pixmap.isNull():
            return QPixmap()
        rect = self.selection_rect()
        return pixmap.copy(rect) if rect is not None else pixmap.copy()

    def selection_rect(self):
        if self.selection_rect_item is None:
            return None
        rect = self.selection_rect_item.rect().normalized()
        rect = rect.intersected(self.pixmap_item.boundingRect())
        if not rect.isValid() or rect.width() < 1 or rect.height() < 1:
            return None
        return rect.toAlignedRect().intersected(self.pixmap_item.pixmap().rect())

    def _ensure_selection(self):
        if self.selection_rect_item is None:
            self.selection_rect_item = ResizableRectItem(
                QRectF(), self.pixmap_item, None
            )
            self.selection_rect_item.setZValue(1)
            self.scene.addItem(self.selection_rect_item)

    def _update_selection_handles(self):
        if self.selection_rect_item is not None:
            self.selection_rect_item.update_handles_pos()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_press_pos = event.position().toPoint()
            self.right_last_pos = self.right_press_pos
            self.right_dragged = False
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, ResizableRectItem):
                super().mousePressEvent(event)
                return

            scene_pos = self.mapToScene(event.position().toPoint())
            pixmap_rect = self.pixmap_item.boundingRect()
            if self.pixmap_item.pixmap().isNull() or not pixmap_rect.contains(scene_pos):
                self.clear_selection()
                event.accept()
                return

            self.selection_start = scene_pos
            self._ensure_selection()
            self.scene.clearSelection()
            self.selection_rect_item.setSelected(True)
            self.selection_rect_item.setRect(QRectF(scene_pos, scene_pos))
            self.selection_rect_item.update_handles_pos()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.right_press_pos is not None:
            current = event.position().toPoint()
            if not self.right_dragged:
                distance = (current - self.right_press_pos).manhattanLength()
                self.right_dragged = distance >= QApplication.startDragDistance()
            if self.right_dragged:
                delta = current - self.right_last_pos
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x()
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y()
                )
            self.right_last_pos = current
            event.accept()
            return

        if self.selection_start is not None:
            current = self.mapToScene(event.position().toPoint())
            rect = QRectF(self.selection_start, current).normalized()
            rect = rect.intersected(self.pixmap_item.boundingRect())
            self.selection_rect_item.setRect(rect)
            self.selection_rect_item.update_handles_pos()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.right_press_pos is not None:
            global_pos = self.viewport().mapToGlobal(event.position().toPoint())
            dragged = self.right_dragged
            self.right_press_pos = None
            self.right_last_pos = None
            self.right_dragged = False
            self.viewport().unsetCursor()
            if not dragged:
                self.context_menu_requested.emit(global_pos)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.selection_start is not None:
            self.selection_start = None
            if self.selection_rect() is None:
                self.clear_selection()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self._update_selection_handles()

    def fit_to_window(self):
        super().fit_to_window()
        self._update_selection_handles()

    def actual_size(self):
        super().actual_size()
        self._update_selection_handles()

    def zoom_in(self):
        super().zoom_in()
        self._update_selection_handles()

    def zoom_out(self):
        super().zoom_out()
        self._update_selection_handles()

    def zoom_200(self):
        if self.pixmap_item.pixmap().isNull():
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        self.scale(2.0, 2.0)
        self.centerOn(center)
        self._update_selection_handles()

class FullScreenViewer(QDialog):
    SLIDESHOW_INTERVAL_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("fullscreenViewer")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.viewer = FullscreenImageViewer()
        self.viewer.setObjectName("fullscreenImageView")
        self.viewer.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewer.installEventFilter(self)
        self.viewer.viewport().installEventFilter(self)
        self.viewer.context_menu_requested.connect(self.show_context_menu)
        self.layout.addWidget(self.viewer)

        self.hud_label = QLabel(self.viewer.viewport())
        self.hud_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hud_label.setContentsMargins(8, 5, 8, 5)
        self.hud_label.setStyleSheet("""
            QLabel {
                color: white;
                background-color: rgba(20, 20, 20, 185);
                border: 1px solid rgba(255, 255, 255, 70);
                padding: 0;
            }
        """)
        self.hud_visible = get_fullscreen_hud_visible()
        self._hud_filename = ""
        self._hud_format = "IMAGE"
        self._hud_width = 0
        self._hud_height = 0
        self.hud_label.setVisible(self.hud_visible)
        
        self.current_image_path = None
        self.slideshow_mode = get_slideshow_mode()
        self.slideshow_random_queue = []
        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.setInterval(self.SLIDESHOW_INTERVAL_MS)
        self.slideshow_timer.timeout.connect(self.advance_slideshow)
        
        self.setup_shortcuts()

    def setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence(Qt.Key.Key_PageDown), self).activated.connect(self.next_image)
        QShortcut(QKeySequence(Qt.Key.Key_PageUp), self).activated.connect(self.prev_image)
        QShortcut(QKeySequence("Ctrl+Home"), self).activated.connect(self.first_image)
        QShortcut(QKeySequence("Ctrl+End"), self).activated.connect(self.last_image)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(self.delete_current_image)
        QShortcut(QKeySequence("Shift+Delete"), self).activated.connect(lambda: self.delete_current_image(permanent=True))
        QShortcut(QKeySequence("Ctrl+C"), self).activated.connect(self.copy_pixels)
        QShortcut(QKeySequence("Ctrl+A"), self).activated.connect(self.select_all_pixels)
        QShortcut(QKeySequence("+"), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("="), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("-"), self).activated.connect(self.zoom_out)

    def rotate_image_90(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'rotate_image_90'):
            self.parent().rotate_image_90()

    def rotate_image_90_left(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'rotate_image_90_left'):
            self.parent().rotate_image_90_left()

    def flip_image_horizontal(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'flip_image_horizontal'):
            self.parent().flip_image_horizontal()

    def flip_image_vertical(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'flip_image_vertical'):
            self.parent().flip_image_vertical()

    def open_adjust_board(self):
        if self.parent() and hasattr(self.parent(), 'open_adjust_board'):
            self.viewer.clear_selection()
            self._run_and_refocus(lambda: self.parent().open_adjust_board(parent_override=self))

    def open_crop_board(self):
        if self.parent() and hasattr(self.parent(), 'open_crop_board'):
            self.viewer.clear_selection()
            self._run_and_refocus(lambda: self.parent().open_crop_board(parent_override=self))

    def select_all_pixels(self):
        self.viewer.select_all()

    def copy_pixels(self):
        pixmap = self.viewer.selected_pixmap()
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)

    def set_slideshow_mode(self, mode):
        self.slideshow_mode = "random" if mode == "random" else "ordered"
        save_slideshow_mode(self.slideshow_mode)

    def start_slideshow(self, mode=None):
        if mode is not None:
            self.set_slideshow_mode(mode)
        self.viewer.clear_selection()
        self.slideshow_random_queue = []
        if self.slideshow_mode == "random":
            parent = self.parent()
            if parent and hasattr(parent, "fullscreen_image_paths"):
                self.slideshow_random_queue = [
                    path for path in parent.fullscreen_image_paths()
                    if path != self.current_image_path
                ]
                random.shuffle(self.slideshow_random_queue)
        self.slideshow_timer.start()

    def stop_slideshow(self):
        self.slideshow_timer.stop()
        self.slideshow_random_queue = []

    def toggle_slideshow(self):
        if self.slideshow_timer.isActive():
            self.stop_slideshow()
        else:
            self.start_slideshow()

    def advance_slideshow(self):
        parent = self.parent()
        if parent is None:
            self.stop_slideshow()
            return

        if self.slideshow_mode == "ordered":
            moved = bool(parent.navigate_fullscreen(1))
        else:
            moved = False
            while self.slideshow_random_queue and not moved:
                target = self.slideshow_random_queue.pop(0)
                if target != self.current_image_path:
                    moved = bool(parent.navigate_fullscreen_to_path(target))
        if not moved:
            self.stop_slideshow()

    def zoom_in(self):
        self.viewer.zoom_in()

    def zoom_out(self):
        self.viewer.zoom_out()

    def zoom_200(self):
        self.viewer.zoom_200()

    def next_image(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'navigate_fullscreen'):
            self.parent().navigate_fullscreen(1)

    def prev_image(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'navigate_fullscreen'):
            self.parent().navigate_fullscreen(-1)

    def first_image(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'navigate_fullscreen'):
            self.parent().navigate_fullscreen('first')

    def last_image(self):
        self.viewer.clear_selection()
        if self.parent() and hasattr(self.parent(), 'navigate_fullscreen'):
            self.parent().navigate_fullscreen('last')

    def delete_current_image(self, permanent=False):
        if self.current_image_path and self.parent() and hasattr(self.parent(), 'delete_selected_files'):
            self.parent().delete_selected_files([self.current_image_path], permanent=permanent, stay_fullscreen=True)

    def set_current_image_path(self, file_path):
        self.current_image_path = file_path
        self._hud_filename = os.path.basename(file_path) if file_path else ""
        extension = os.path.splitext(file_path or "")[1].lstrip(".")
        self._hud_format = extension.upper() or "IMAGE"
        self.refresh_hud()

    def set_display_pixmap(self, pixmap):
        self.viewer.set_pixmap(pixmap)
        self.update_hud_from_pixmap(pixmap)

    def load_image(self, file_path, prefetched_image=None):
        self.set_current_image_path(file_path)
        if prefetched_image is not None and not prefetched_image.isNull():
            pixmap = QPixmap.fromImage(prefetched_image)
            self.set_display_pixmap(pixmap)
        else:
            self.viewer.clear_image()
            self.viewer.load_image(file_path)
            self.update_hud_from_pixmap(self.viewer.pixmap_item.pixmap())
        self.showFullScreen()
        QTimer.singleShot(0, self.fit_after_fullscreen_show)
        self.refresh_hud()
        self.refocus()

    def fit_after_fullscreen_show(self):
        if self.isVisible() and not self.viewer.pixmap_item.pixmap().isNull():
            self.viewer.fit_to_window()

    def update_hud_from_pixmap(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self._hud_width = pixmap.width()
            self._hud_height = pixmap.height()
        else:
            self._hud_width = 0
            self._hud_height = 0
        self.refresh_hud()

    def refresh_hud(self):
        if not self.hud_visible:
            self.hud_label.hide()
            return

        viewport_width = max(1, self.viewer.viewport().width())
        maximum_width = max(80, min(viewport_width - 24, int(viewport_width * 0.6)))
        text_width = max(32, maximum_width - 16)
        metrics = QFontMetrics(self.hud_label.font())
        filename = metrics.elidedText(
            self._hud_filename or "Unknown file",
            Qt.TextElideMode.ElideMiddle,
            text_width,
        )
        if self._hud_width and self._hud_height:
            details = f"{self._hud_format}  {self._hud_width} x {self._hud_height}"
        else:
            details = f"{self._hud_format}  resolution unavailable"
        self.hud_label.setMaximumWidth(maximum_width)
        self.hud_label.setText(f"{filename}\n{details}")
        self.hud_label.adjustSize()
        self.hud_label.move(12, 12)
        self.hud_label.show()
        self.hud_label.raise_()

    def set_hud_visible(self, visible, persist=True):
        self.hud_visible = bool(visible)
        if persist:
            set_fullscreen_hud_visible(self.hud_visible)
        self.refresh_hud()

    def toggle_hud(self):
        self.set_hud_visible(not self.hud_visible)

    def eventFilter(self, obj, event):
        if obj in (self.viewer, self.viewer.viewport()) and event.type() == QEvent.Type.KeyPress:
            if self.handle_key_press(event):
                event.accept()
                return True

        if obj == self.viewer.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                if event.angleDelta().y() < 0:
                    self.next_image()
                else:
                    self.prev_image()
                event.accept()
                return True
        if obj == self.viewer.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.refresh_hud)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Print:
            event.ignore()
            return
        if self.handle_key_press(event):
            event.accept()
            return
        self.viewer.keyPressEvent(event)

    def handle_key_press(self, event):
        key = event.key()
        if key == Qt.Key.Key_Print:
            return False
        text = event.text().lower()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        plain_key = not ctrl and not shift and not alt

        if key == Qt.Key.Key_Escape:
            self.stop_slideshow()
            if self.parent() and hasattr(self.parent(), 'leave_fullscreen'):
                if not self.parent().leave_fullscreen(commit_current=False):
                    return True
            self.close()
            return True
        if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.stop_slideshow()
            if self.parent() and hasattr(self.parent(), 'leave_fullscreen'):
                if not self.parent().leave_fullscreen(commit_current=True):
                    return True
            self.close()
            return True
        if ctrl and key == Qt.Key.Key_Home:
            self.first_image()
            return True
        if ctrl and key == Qt.Key.Key_End:
            self.last_image()
            return True
        if ctrl and key == Qt.Key.Key_H:
            self.toggle_hud()
            return True
        if ctrl and key == Qt.Key.Key_C:
            self.copy_pixels()
            return True
        if ctrl and key == Qt.Key.Key_A:
            self.select_all_pixels()
            return True
        if ctrl and key == Qt.Key.Key_X:
            self._run_and_refocus(self.parent().cut_to_clipboard)
            return True
        if ctrl and key == Qt.Key.Key_V:
            self._run_and_refocus(self.parent().paste_from_clipboard)
            return True
        if key == Qt.Key.Key_F2:
            self._run_and_refocus(lambda: self.parent().rename_file(parent_override=self))
            return True
        if key == Qt.Key.Key_F3:
            self.parent().open_in_associated_program(self.current_image_path, parent_override=self)
            return True
        if key == Qt.Key.Key_F4:
            if self.parent().supports_associated_editor():
                self.parent().open_in_associated_editor(self.current_image_path, parent_override=self)
            return True
        if key == Qt.Key.Key_PageDown:
            self.next_image()
            return True
        if key == Qt.Key.Key_PageUp:
            self.prev_image()
            return True
        if key == Qt.Key.Key_Delete:
            self.delete_current_image(permanent=shift)
            return True
        if key == Qt.Key.Key_Pause:
            self.toggle_slideshow()
            return True

        if not plain_key:
            return False

        if key == Qt.Key.Key_Asterisk:
            self.viewer.fit_to_window()
            return True
        if key == Qt.Key.Key_Slash:
            self.viewer.actual_size()
            return True
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            return True
        if key == Qt.Key.Key_Minus:
            self.zoom_out()
            return True
        if key in (Qt.Key.Key_5, Qt.Key.Key_Clear) or text == "5":
            self.zoom_200()
            return True
        if key == Qt.Key.Key_P or text == "p":
            self.prev_image()
            return True
        if key == Qt.Key.Key_N or text == "n":
            self.next_image()
            return True
        if key == Qt.Key.Key_C or text == "c":
            self._run_and_refocus(
                lambda: self.parent().open_copy_dialog(parent_override=self),
                delayed=False,
            )
            return True
        if key == Qt.Key.Key_M or text == "m":
            self._run_and_refocus(
                lambda: self.parent().open_move_dialog(parent_override=self),
                delayed=False,
            )
            return True
        if key == Qt.Key.Key_X or text == "x":
            self.open_crop_board()
            return True
        if key == Qt.Key.Key_A or text == "a":
            self.open_adjust_board()
            return True
        if key == Qt.Key.Key_R or text == "r":
            self.rotate_image_90()
            return True
        if key == Qt.Key.Key_L or text == "l":
            self.rotate_image_90_left()
            return True
        if key == Qt.Key.Key_H or text == "h":
            self.flip_image_horizontal()
            return True
        if key == Qt.Key.Key_V or text == "v":
            self.flip_image_vertical()
            return True

        return False

    def refocus(self):
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QApplication.setActiveWindow(self)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        self.viewer.viewport().setFocus(Qt.FocusReason.OtherFocusReason)

    def refocus_later(self):
        self.refocus()
        QTimer.singleShot(0, self.refocus)
        QTimer.singleShot(50, self.refocus)
        QTimer.singleShot(150, self.refocus)
        QTimer.singleShot(300, self.refocus)

    def _run_and_refocus(self, action_func, delayed=True):
        action_func()
        if delayed:
            self.refocus_later()
        else:
            self.refocus()

    def closeEvent(self, event):
        self.stop_slideshow()
        super().closeEvent(event)

    def show_context_menu(self, global_pos):
        if not self.current_image_path:
            return

        slideshow_was_active = self.slideshow_timer.isActive()
        if slideshow_was_active:
            self.slideshow_timer.stop()
        slideshow_stop_requested = False

        menu = QMenu(self)
        

        main_window = self.parent()

        if main_window:
            hud_action = QAction("Show Image Info\tCtrl+H", self, checkable=True)
            hud_action.setChecked(self.hud_visible)
            hud_action.toggled.connect(self.set_hud_visible)
            menu.addAction(hud_action)

            slideshow_menu = menu.addMenu("Slideshow (Pause)")
            slideshow_group = QActionGroup(slideshow_menu)
            slideshow_group.setExclusive(True)

            ordered_action = QAction("In order", slideshow_menu, checkable=True)
            ordered_action.setChecked(self.slideshow_mode == "ordered")
            ordered_action.triggered.connect(
                lambda checked=False: self.start_slideshow("ordered")
            )
            slideshow_group.addAction(ordered_action)
            slideshow_menu.addAction(ordered_action)

            random_action = QAction("Randomized", slideshow_menu, checkable=True)
            random_action.setChecked(self.slideshow_mode == "random")
            random_action.triggered.connect(
                lambda checked=False: self.start_slideshow("random")
            )
            slideshow_group.addAction(random_action)
            slideshow_menu.addAction(random_action)

            if slideshow_was_active:
                slideshow_menu.addSeparator()
                stop_action = QAction("Stop", slideshow_menu)
                def stop_from_menu():
                    nonlocal slideshow_stop_requested
                    slideshow_stop_requested = True
                    self.stop_slideshow()
                stop_action.triggered.connect(stop_from_menu)
                slideshow_menu.addAction(stop_action)
            menu.addSeparator()

            next_action = QAction("Next Image\tPgDown / N", self)
            next_action.triggered.connect(self.next_image)
            menu.addAction(next_action)
            
            prev_action = QAction("Previous Image\tPgUp / P", self)
            prev_action.triggered.connect(self.prev_image)
            menu.addAction(prev_action)
            
            first_action = QAction("First Image\tCtrl+Home", self)
            first_action.triggered.connect(self.first_image)
            menu.addAction(first_action)

            last_action = QAction("Last Image\tCtrl+End", self)
            last_action.triggered.connect(self.last_image)
            menu.addAction(last_action)
            
            menu.addSeparator()

            copy_pixels_action = QAction("Copy to Clipboard\tCtrl+C", self)
            copy_pixels_action.triggered.connect(self.copy_pixels)
            menu.addAction(copy_pixels_action)

            menu.addSeparator()

            copy_action = QAction("Copy To... (C)", self)
            copy_action.triggered.connect(lambda: self._run_and_refocus(
                lambda: main_window.open_copy_dialog(parent_override=self),
                delayed=False,
            ))
            menu.addAction(copy_action)
            
            move_action = QAction("Move To... (M)", self)
            move_action.triggered.connect(lambda: self._run_and_refocus(
                lambda: main_window.open_move_dialog(parent_override=self),
                delayed=False,
            ))
            menu.addAction(move_action)

            main_window.add_open_with_menu(menu, self.current_image_path, parent_override=self)
            main_window.add_send_to_menu(menu, [self.current_image_path], parent_override=self)
            main_window.add_windows_image_actions(
                menu, self.current_image_path, parent_override=self
            )

            delete_action = QAction("Delete", self)
            delete_action.triggered.connect(self.delete_current_image)
            menu.addAction(delete_action)
            
            crop_action = QAction("Crop (X)", self)
            crop_action.triggered.connect(self.open_crop_board)
            menu.addAction(crop_action)
            
            menu.addSeparator()
            
            rotate_left_action = QAction("Rotate 90 degrees left\tL", self)
            rotate_left_action.triggered.connect(self.rotate_image_90_left)
            menu.addAction(rotate_left_action)

            rotate_action = QAction("Rotate 90 degrees right\tR", self)
            rotate_action.triggered.connect(self.rotate_image_90)
            menu.addAction(rotate_action)
            
            flip_h_action = QAction("Flip Horizontal\tH", self)
            flip_h_action.triggered.connect(self.flip_image_horizontal)
            menu.addAction(flip_h_action)
            
            flip_v_action = QAction("Flip Vertical\tV", self)
            flip_v_action.triggered.connect(self.flip_image_vertical)
            menu.addAction(flip_v_action)
            
            menu.addSeparator()
            
            adjust_action = QAction("Adjust Colors & Size (A)", self)
            adjust_action.triggered.connect(lambda: self._run_and_refocus(lambda: main_window.open_adjust_board(parent_override=self)))
            menu.addAction(adjust_action)

        menu.exec(global_pos)
        if (
            slideshow_was_active and
            not slideshow_stop_requested and
            not self.slideshow_timer.isActive() and
            self.isVisible()
        ):
            self.slideshow_timer.start()
