import os

from PyQt6.QtGui import QPixmap

from ui.gif_playback import GifPlayback
from ui.image_viewer import ImageViewer
from utils.file_ops import get_image_settings
from utils.image_loading import MAX_PREFETCH_IMAGE_BYTES, MIB


class GifPreviewViewer(ImageViewer):
    """Play the selected GIF without changing the browser preview's zoom or edits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gif_enabled = False
        self._gif_paused = False
        self._gif_source = None
        self._first_frame = QPixmap()
        self._playback = None
        self._requested = False
        self._byte_limit = self._playback_limit(get_image_settings())

    @staticmethod
    def _playback_limit(settings):
        return min(MAX_PREFETCH_IMAGE_BYTES, settings["max_decoded_image_mb"] * MIB)

    def apply_image_settings(self, settings):
        super().apply_image_settings(settings)
        if "max_decoded_image_mb" in settings:
            limit = self._playback_limit(settings)
            if limit != self._byte_limit:
                self.shutdown_gif_playback()
                self._byte_limit = limit
                self._sync_playback()

    def set_gif_playback(self, enabled):
        if self._gif_enabled != enabled:
            self._gif_enabled = enabled
            self._sync_playback()

    def set_gif_playback_paused(self, paused):
        if self._gif_paused != paused:
            self._gif_paused = paused
            self._sync_playback()

    def load_image(self, file_path):
        loaded = super().load_image(file_path)
        if loaded:
            self._set_source(file_path)
        return loaded

    def set_source_pixmap(self, file_path, pixmap):
        self.set_pixmap(pixmap)
        if not pixmap.isNull():
            self._set_source(file_path)

    def _set_source(self, file_path):
        if os.path.splitext(file_path)[1].lower() == ".gif":
            self._gif_source = os.fspath(file_path)
            self._first_frame = self.pixmap_item.pixmap()
            self._sync_playback()

    def rename_gif_source(self, old_path, new_path):
        if self._gif_source and os.path.normcase(self._gif_source) == os.path.normcase(old_path):
            self._forget_source()
            self._set_source(new_path)

    def _forget_source(self):
        if self._gif_source:
            self._stop_playback()
            self._gif_source = None
            self._first_frame = QPixmap()

    def _sync_playback(self):
        if not self._gif_source:
            return
        if (not self._gif_enabled or self._gif_paused or not self.isVisible()
                or self.viewport().width() < 2 or self.viewport().height() < 2):
            self._stop_playback()
            return
        if self._requested:
            return
        if self._playback is None:
            self._playback = GifPlayback(self, max_players=1, byte_limit=self._byte_limit)
            self._playback.frames_changed.connect(self._show_frames)
        self._requested = True
        self._playback.set_sources([self._gif_source])

    def _show_frames(self, frames):
        if self.sender() is not self._playback or not self._requested:
            return
        if self._gif_source not in frames:
            return
        frame = frames[self._gif_source]
        if frame is not None and not frame.isNull():
            # The pixmap has the source dimensions. Replacing it in place leaves
            # the existing fit, manual zoom, and pan untouched between frames.
            self.pixmap_item.setPixmap(QPixmap.fromImage(frame))
        else:
            self.pixmap_item.setPixmap(self._first_frame)

    def _stop_playback(self):
        if self._requested:
            self._requested = False
            self._playback.clear()
            self.pixmap_item.setPixmap(self._first_frame)

    def shutdown_gif_playback(self):
        self._stop_playback()
        if self._playback is not None:
            self._playback.shutdown()
            self._playback.deleteLater()
            self._playback = None

    def clear_image(self):
        self._forget_source()
        super().clear_image()

    def set_pixmap(self, pixmap):
        # An ordinary pixmap can be a still edit, a video frame, or a placeholder.
        self._forget_source()
        super().set_pixmap(pixmap)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stop_playback()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.shutdown_gif_playback()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_playback()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_playback()
