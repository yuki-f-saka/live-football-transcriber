import unittest
from collections import Counter

import numpy as np

from football_transcriber.audio import Gain, InputMonitor


class GainTests(unittest.TestCase):
    def test_step_clamp_and_callback(self):
        seen = []
        g = Gain(1.0, on_change=seen.append)
        self.assertAlmostEqual(g.up(), 1.1)
        self.assertAlmostEqual(g.down(), 1.0)
        g.set(10)
        self.assertEqual(g.value, Gain.MAX)
        g.set(-1)
        self.assertEqual(g.value, Gain.MIN)
        self.assertEqual(seen, [1.1, 1.0, 5.0, 0.0])

    def test_mute_toggle_restores(self):
        g = Gain(1.5)
        g.toggle_mute()
        self.assertEqual(g.value, 0.0)
        self.assertIn("muted", g.label())
        g.toggle_mute()
        self.assertEqual(g.value, 1.5)

    def test_apply_scales_and_clips(self):
        g = Gain(2.0)
        out = g.apply(np.array([0.25, 0.75, -0.75], dtype=np.float32))
        np.testing.assert_allclose(out, [0.5, 1.0, -1.0])
        g = Gain(1.0)
        x = np.array([0.3], dtype=np.float32)
        self.assertIs(g.apply(x), x)  # unity gain is a no-op on the real-time path


class InputMonitorTests(unittest.TestCase):
    """Issue #27: the monitor must name the reason no subtitles are appearing."""

    def monitor(self, threshold=0.03, **kw):
        self.badges = []
        return InputMonitor("BlackHole 2ch", threshold, Gain(1.0),
                            interval=20.0, on_warning=self.badges.append, **kw)

    def test_no_blocks_means_a_dead_stream(self):
        msg, badge = self.monitor()._diagnose(0.0, 0, 0, Counter())
        self.assertIn("No audio delivered", msg)
        self.assertEqual(badge, "⚠ no audio")

    def test_digital_silence_points_at_routing(self):
        msg, badge = self.monitor()._diagnose(0.0002, 400, 0, Counter())
        self.assertIn("Silence", msg)
        self.assertIn("Multi-Output", msg)
        self.assertEqual(badge, "⚠ no audio")

    def test_signal_below_threshold_is_distinguished_from_silence(self):
        msg, badge = self.monitor()._diagnose(0.018, 400, 0, Counter())
        self.assertIn("below the speech threshold", msg)
        self.assertIn("0.0180", msg)
        self.assertIn("0.030", msg)
        self.assertIn("quiet", badge)

    def test_rejected_transcriptions_are_broken_down(self):
        msg, badge = self.monitor()._diagnose(0.12, 400, 6, Counter({"no_speech": 3, "prompt_echo": 2}))
        self.assertIn("no_speech=3, prompt_echo=2", msg)
        self.assertEqual(badge, "⚠ all filtered")

    def test_streaming_mode_has_no_threshold_branch(self):
        # threshold=None: Silero owns the VAD, so "below threshold" is meaningless.
        msg, _ = self.monitor(threshold=None)._diagnose(0.018, 400, 0, Counter())
        self.assertNotIn("threshold", msg)

    def test_report_is_silent_while_text_flows(self):
        m = self.monitor()
        m.note_block(0.2)
        m.note_speech()
        m.note_text()
        with self.assertNoLogs("football_transcriber.audio", level="WARNING"):
            m._report()
        self.assertEqual(self.badges, [])

    def test_report_warns_and_resets_counters(self):
        m = self.monitor()
        for _ in range(3):
            m.note_block(0.001)
        m.note_reject("hallucination")
        with self.assertLogs("football_transcriber.audio", level="WARNING"):
            m._report()
        self.assertEqual(len(self.badges), 1)
        # counters start fresh, so the next window is judged on its own
        self.assertEqual((m._peak, m._blocks, m._speech, m._texts, m._rejects), (0, 0, 0, 0, Counter()))

    def test_note_block_keeps_the_peak(self):
        m = self.monitor()
        for rms in (0.01, 0.4, 0.02):
            m.note_block(rms)
        self.assertAlmostEqual(m._peak, 0.4)
        self.assertEqual(m._blocks, 3)


if __name__ == "__main__":
    unittest.main()
