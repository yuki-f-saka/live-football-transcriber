import unittest

import numpy as np

from football_transcriber.audio import Gain


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


if __name__ == "__main__":
    unittest.main()
