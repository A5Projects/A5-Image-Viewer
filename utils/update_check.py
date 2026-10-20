"""An explicit, read-only GitHub release check; no requests until check() is called."""

import json
import re

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from utils.app_info import APP_VERSION, RELEASE_TAG


LATEST_RELEASE_URL = "https://api.github.com/repos/A5Projects/A5-Image-Viewer/releases/latest"
MAX_RESPONSE_BYTES = 1024 * 1024


def release_key(tag):
    """Compare version, optional dated update, and same-day rebuild numerically."""
    if not isinstance(tag, str):
        raise ValueError("Unrecognized release version.")
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(\d{8})(?:\.(\d+))?)?", tag)
    if match is None:
        raise ValueError("Unrecognized release version.")
    return tuple(int(part or 0) for part in match.groups())


def release_message(payload, current_tag=RELEASE_TAG):
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("No stable release information was returned.")
    tag = payload.get("tag_name")
    if release_key(tag) > release_key(current_tag):
        return f"New version available: {tag}. See Releases below."
    return "You are up to date. No newer release is available."


class ReleaseChecker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = None
        self.reply = None
        self.data = bytearray()
        self.failure = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self._timeout)

    def check(self):
        if self.reply is not None:
            return
        # Even the network manager is created only after the user's button click.
        if self.manager is None:
            self.manager = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(LATEST_RELEASE_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"A5ImageViewer/{APP_VERSION}".encode("ascii"))
        request.setTransferTimeout(15000)
        self.data.clear()
        self.failure = None
        self.reply = self.manager.get(request)
        self.reply.setReadBufferSize(64 * 1024)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.timer.start()

    def _read(self):
        if self.reply is None or self.failure is not None:
            return
        self.data.extend(bytes(self.reply.readAll()))
        if len(self.data) > MAX_RESPONSE_BYTES:
            self.failure = "Could not check for updates: response too large. Try again later."
            self.reply.abort()

    def _timeout(self):
        if self.reply is not None:
            self.failure = "Could not check for updates: connection timed out. Try again later."
            self.reply.abort()

    def _finished(self):
        if self.reply is None:
            return
        self.timer.stop()
        reply, self.reply = self.reply, None
        self.data.extend(bytes(reply.readAll()))
        if len(self.data) > MAX_RESPONSE_BYTES:
            self.failure = "Could not check for updates: response too large. Try again later."
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if self.failure:
            message = self.failure
        elif status in (403, 429):
            message = "Could not check for updates: GitHub request limit reached. Try again later."
        elif status == 404:
            message = "No published release is available."
        elif reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
            message = "Could not check for updates. Check your connection and try again."
        else:
            try:
                message = release_message(json.loads(self.data))
            except (ValueError, UnicodeError):
                message = "Could not read the release version. Please use the Releases link."
        reply.deleteLater()
        self.data.clear()
        self.finished.emit(message)

    def cancel(self):
        self.timer.stop()
        if self.reply is not None:
            reply, self.reply = self.reply, None
            reply.abort()
            reply.deleteLater()
        self.data.clear()
