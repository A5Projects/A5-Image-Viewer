import time

from PyQt6.QtTest import QTest


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for Qt operation")
        QTest.qWait(10)
