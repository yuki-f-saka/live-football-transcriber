import unittest

from football_transcriber.macos import _BITS, OVERLAY_BEHAVIOR, _LogOnce, describe_behavior


class OverlayBehaviorTests(unittest.TestCase):
    """The intended collectionBehavior, checkable without a GUI or PyObjC."""

    def test_includes_the_flags_that_reach_other_spaces(self):
        self.assertTrue(OVERLAY_BEHAVIOR & _BITS["CanJoinAllSpaces"])
        self.assertTrue(OVERLAY_BEHAVIOR & _BITS["FullScreenAuxiliary"])
        self.assertTrue(OVERLAY_BEHAVIOR & _BITS["IgnoresCycle"])

    def test_excludes_stationary(self):
        """#33: Stationary keeps the window on the desktop Space, which is the bug."""
        self.assertFalse(OVERLAY_BEHAVIOR & _BITS["Stationary"])

    def test_excludes_fullscreen_primary(self):
        """Qt's default. It gives the window its own Space instead of floating over one."""
        self.assertFalse(OVERLAY_BEHAVIOR & _BITS["FullScreenPrimary"])

    def test_exact_value(self):
        self.assertEqual(OVERLAY_BEHAVIOR, 0x141)


class DescribeBehaviorTests(unittest.TestCase):
    def test_decodes_known_bits(self):
        self.assertEqual(
            describe_behavior(OVERLAY_BEHAVIOR),
            "0x141 = CanJoinAllSpaces | IgnoresCycle | FullScreenAuxiliary",
        )

    def test_qt_default_is_reported_as_fullscreen_primary(self):
        self.assertEqual(describe_behavior(0x80), "0x80 = FullScreenPrimary")

    def test_empty(self):
        self.assertEqual(describe_behavior(0), "0x0 = (none)")

    def test_unknown_bits_are_kept_visible(self):
        self.assertEqual(describe_behavior(1 << 20), "0x100000 = 0x100000")


class LogOnceTests(unittest.TestCase):
    """The watchdog runs every 2 s; a permanent failure must not log every tick."""

    def test_repeated_state_is_reported_once(self):
        gate = _LogOnce()
        self.assertTrue(gate.is_new(0x80))
        self.assertFalse(gate.is_new(0x80))
        self.assertFalse(gate.is_new(0x80))

    def test_a_different_state_is_reported_again(self):
        gate = _LogOnce()
        gate.is_new(0x80)
        self.assertTrue(gate.is_new(0x1))

    def test_reset_makes_the_next_report_new(self):
        """A successful repair resets the gate, so the next revert is logged."""
        gate = _LogOnce()
        gate.is_new(0x80)
        gate.reset()
        self.assertTrue(gate.is_new(0x80))


if __name__ == "__main__":
    unittest.main()
