"""Recognize deliberate horizontal wheel gestures without stealing vertical scrolls."""
import time
from PyQt6.QtCore import Qt


class SwipeNavigation:
    # Windows drivers may omit scroll phases. Group their wheel events by idle time.
    IDLE_SECONDS = 0.35
    PIXEL_THRESHOLD = 80
    ANGLE_THRESHOLD = 120

    def __init__(self):
        self.last_event = None
        self.reset()

    def reset(self):
        self.x = self.y = 0
        self.vertical = False
        self.fired = False

    def feed(self, event, now=None):
        now = time.monotonic() if now is None else now
        phase = event.phase()
        no_phase = phase == Qt.ScrollPhase.NoScrollPhase
        if (phase == Qt.ScrollPhase.ScrollBegin or self.last_event is None or
                (no_phase and now - self.last_event >= self.IDLE_SECONDS)):
            self.reset()
        self.last_event = now
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            self.vertical = True
            return False, 0
        # Momentum cannot initiate navigation. Retain the latch through ScrollEnd
        # because some drivers send trailing events after the fingers lift.
        if phase in (Qt.ScrollPhase.ScrollMomentum, Qt.ScrollPhase.ScrollEnd):
            return self.fired, 0
        if self.vertical:
            return False, 0
        delta = event.pixelDelta()
        pixels = not delta.isNull()
        if not pixels:
            delta = event.angleDelta()
        if self.fired:
            # Do not swallow an immediately following vertical scroll, even if a
            # phase-less driver has not yet left the idle-time gesture window.
            return abs(delta.x()) >= abs(delta.y()), 0
        self.x += delta.x()
        self.y += abs(delta.y())
        threshold = self.PIXEL_THRESHOLD if pixels else self.ANGLE_THRESHOLD
        if self.y >= threshold / 4 and self.y >= abs(self.x):
            self.vertical = True
            return False, 0
        horizontal = abs(self.x) >= 2 * self.y and self.x != 0
        if horizontal and abs(self.x) >= threshold:
            self.fired = True
            # Use delivered scroll direction, respecting the OS scrolling setting.
            return True, -1 if self.x > 0 else 1
        return horizontal, 0
