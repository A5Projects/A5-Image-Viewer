import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication
from ui.swipe_navigation import SwipeNavigation


def wheel(x=0, y=0, phase=Qt.ScrollPhase.NoScrollPhase, pixels=True,
          modifiers=Qt.KeyboardModifier.NoModifier, inverted=False):
    delta = QPoint(x, y)
    return QWheelEvent(QPointF(20, 20), QPointF(20, 20),
                      delta if pixels else QPoint(),
                      QPoint() if pixels else delta, Qt.MouseButton.NoButton,
                      modifiers, phase, inverted)


class SwipeNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.swipe = SwipeNavigation()

    def test_threshold_both_directions_and_once_per_phased_swipe(self):
        for sign in (1, -1):
            self.swipe.feed(wheel(phase=Qt.ScrollPhase.ScrollBegin), now=0)
            self.assertEqual(self.swipe.feed(wheel(sign * 40, phase=Qt.ScrollPhase.ScrollUpdate), now=.1), (True, 0))
            self.assertEqual(self.swipe.feed(wheel(sign * 40, phase=Qt.ScrollPhase.ScrollUpdate), now=.2), (True, -sign))
            for phase in (Qt.ScrollPhase.ScrollUpdate, Qt.ScrollPhase.ScrollMomentum, Qt.ScrollPhase.ScrollEnd):
                self.assertEqual(self.swipe.feed(wheel(sign * 500, phase=phase), now=3), (True, 0))

    def test_phase_less_angle_events_latch_until_idle(self):
        self.assertEqual(self.swipe.feed(wheel(60, pixels=False), now=0), (True, 0))
        self.assertEqual(self.swipe.feed(wheel(60, pixels=False), now=.1), (True, -1))
        for i in range(2, 10):
            self.assertEqual(self.swipe.feed(wheel(-120, pixels=False), now=i / 10), (True, 0))
        self.assertEqual(self.swipe.feed(wheel(-120, pixels=False), now=1.5), (True, 1))

    def test_vertical_and_diagonal_gestures_are_never_navigation(self):
        for x, y in ((0, 120), (30, 120), (70, 70)):
            self.swipe = SwipeNavigation()
            self.assertEqual(self.swipe.feed(wheel(x, y), now=0), (False, 0))
            self.assertEqual(self.swipe.feed(wheel(400, 0), now=.1), (False, 0))

    def test_jitter_modifiers_and_unclaimed_momentum(self):
        self.assertEqual(self.swipe.feed(wheel(4, 12), now=0), (False, 0))
        self.assertEqual(self.swipe.feed(wheel(4, 24), now=.1), (False, 0))
        for modifier in (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier):
            self.swipe = SwipeNavigation()
            self.assertEqual(self.swipe.feed(wheel(300, modifiers=modifier), now=0), (False, 0))
            self.assertEqual(self.swipe.feed(wheel(300), now=.1), (False, 0))
        self.swipe = SwipeNavigation()
        self.assertEqual(self.swipe.feed(wheel(300, phase=Qt.ScrollPhase.ScrollMomentum)), (False, 0))

    def test_vertical_scroll_after_navigation_is_not_swallowed(self):
        self.swipe.feed(wheel(120, pixels=False), now=0)
        self.assertEqual(self.swipe.feed(wheel(0, -120, pixels=False), now=.1), (False, 0))
        self.assertEqual(self.swipe.feed(wheel(120, pixels=False), now=.2), (True, 0))

    def test_delivered_direction_is_not_inverted_twice(self):
        self.assertEqual(self.swipe.feed(wheel(80, inverted=True)), (True, -1))
