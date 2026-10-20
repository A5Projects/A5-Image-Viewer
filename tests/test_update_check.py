import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QByteArray, QObject, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QApplication

from ui.about_dialog import AboutDialog
from utils import file_ops
from utils.app_info import RELEASE_TAG
from utils.update_check import LATEST_RELEASE_URL, MAX_RESPONSE_BYTES, release_message


class FakeReply(QObject):
    readyRead = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.data = b""
        self.status = 200
        self.code = QNetworkReply.NetworkError.NoError
        self.aborted = False

    def setReadBufferSize(self, size):
        pass

    def readAll(self):
        data, self.data = self.data, b""
        return QByteArray(data)

    def attribute(self, attribute):
        return self.status

    def error(self):
        return self.code

    def abort(self):
        self.aborted = True
        self.code = QNetworkReply.NetworkError.OperationCanceledError
        self.finished.emit()

    def complete(self, data, status=200, error=QNetworkReply.NetworkError.NoError):
        self.data = data
        self.status = status
        self.code = error
        self.readyRead.emit()
        if not self.aborted:
            self.finished.emit()


class UpdateCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = patch.object(file_ops, "CONFIG_FILE", os.path.join(self.temp.name, "config.json"))
        self.config.start()
        self.network = patch("utils.update_check.QNetworkAccessManager")
        self.manager_class = self.network.start()
        self.reply = FakeReply()
        self.manager_class.return_value.get.return_value = self.reply
        self.dialog = AboutDialog()

    def tearDown(self):
        self.dialog.close()
        self.app.processEvents()
        self.network.stop()
        self.config.stop()
        self.temp.cleanup()

    def test_open_and_close_about_never_creates_network_manager(self):
        self.dialog.show()
        self.app.processEvents()
        self.dialog.close()
        self.manager_class.assert_not_called()

    def test_button_starts_one_request_and_displays_new_version(self):
        self.dialog.update_button.click()
        self.assertFalse(self.dialog.update_button.isEnabled())
        self.assertIn("Checking", self.dialog.update_status.text())
        self.dialog.update_button.click()
        manager = self.manager_class.return_value
        manager.get.assert_called_once()
        request = manager.get.call_args.args[0]
        self.assertEqual(request.url().toString(), LATEST_RELEASE_URL)
        self.assertEqual(request.transferTimeout(), 15000)
        self.reply.complete(json.dumps({"tag_name": "v2.0.0"}).encode())
        self.assertIn("New version available: v2.0.0", self.dialog.update_status.text())
        self.assertTrue(self.dialog.update_button.isEnabled())
        self.assertFalse(self.dialog.release_checker.timer.isActive())

    def test_current_version_message_and_retry_only_when_clicked(self):
        self.dialog.update_button.click()
        self.reply.complete(json.dumps({"tag_name": RELEASE_TAG}).encode())
        self.assertIn("up to date", self.dialog.update_status.text())
        self.app.processEvents()
        self.manager_class.return_value.get.assert_called_once()
        second = FakeReply()
        self.manager_class.return_value.get.return_value = second
        self.dialog.update_button.click()
        second.complete(b'{"tag_name": "v2.0.0"}')
        self.assertEqual(self.manager_class.return_value.get.call_count, 2)

    def test_failure_cases_do_not_claim_up_to_date(self):
        cases = [
            (b"{}", 200, QNetworkReply.NetworkError.NoError, "Could not read"),
            (b"not json", 200, QNetworkReply.NetworkError.NoError, "Could not read"),
            (b"[]", 200, QNetworkReply.NetworkError.NoError, "Could not read"),
            (b"", 403, QNetworkReply.NetworkError.ContentAccessDenied, "request limit"),
            (b"", 404, QNetworkReply.NetworkError.ContentNotFoundError, "No published release"),
            (b"", None, QNetworkReply.NetworkError.HostNotFoundError, "connection"),
            (b"x" * (MAX_RESPONSE_BYTES + 1), 200, QNetworkReply.NetworkError.NoError, "too large"),
        ]
        for data, status, error, message in cases:
            with self.subTest(message=message, status=status):
                reply = FakeReply()
                self.manager_class.return_value.get.return_value = reply
                self.dialog.update_button.click()
                reply.complete(data, status, error)
                self.assertIn(message, self.dialog.update_status.text())
                self.assertTrue(self.dialog.update_button.isEnabled())

    def test_timeout_and_close_abort_without_background_retry(self):
        self.dialog.update_button.click()
        self.dialog.release_checker.timer.timeout.emit()
        self.assertTrue(self.reply.aborted)
        self.assertIn("timed out", self.dialog.update_status.text())
        second = FakeReply()
        self.manager_class.return_value.get.return_value = second
        self.dialog.update_button.click()
        self.dialog.reject()
        self.assertTrue(second.aborted)
        self.assertIsNone(self.dialog.release_checker.reply)
        self.assertFalse(self.dialog.release_checker.timer.isActive())
        self.app.processEvents()
        self.assertEqual(self.manager_class.return_value.get.call_count, 2)

    def test_numeric_version_date_and_same_day_rebuild_comparison(self):
        for current, latest, newer in (
            ("v1.0.0-20260922", "v1.0.0-20260922.1", True),
            ("v1.0.0-20260922.9", "v1.0.0-20260922.10", True),
            ("v1.0.0-20260922.1", "v1.0.0-20261016", True),
            ("v1.0.0-20260922.1", "v1.0.0-20260922.1", False),
            ("v1.0.0-20261016", "v1.0.0-20260922", False),
            ("v1.9.0-20261016", "v1.10.0", True),
            ("v2.0.0", "v1.0.0-20271016", False),
        ):
            with self.subTest(current=current, latest=latest):
                message = release_message({"tag_name": latest}, current)
                self.assertEqual("New version available" in message, newer)
        for payload in ({"tag_name": "nightly"}, {"tag_name": "v2.0.0", "prerelease": True}):
            with self.assertRaises(ValueError):
                release_message(payload)
