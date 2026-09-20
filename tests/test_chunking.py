"""Issue #30: a force-flush must not cut in the middle of a word.

The buffers here are synthetic: "speech" is white noise well above the RMS
threshold, a "gap" is near-digital silence. That is enough to exercise every
decision :func:`split_for_flush` makes, and it runs without audio hardware.
"""

import unittest

import numpy as np

from football_transcriber.chunking import split_for_flush

SR = 16000
THRESHOLD = 0.03
LOUD = 0.2
QUIET = 0.001


def signal(seconds: float, amplitude: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(seconds * SR)) * amplitude).astype(np.float32)


def speech_with_gap(total: float, gap_at: float, gap_len: float = 0.1) -> np.ndarray:
    buf = signal(total, LOUD)
    start = int(gap_at * SR)
    buf[start:start + int(gap_len * SR)] = signal(gap_len, QUIET)
    return buf


class SplitForFlushTests(unittest.TestCase):
    def test_cuts_at_a_gap_instead_of_at_the_end(self):
        """A pause between words 0.3 s before the end is where the cut belongs."""
        buf = speech_with_gap(total=5.0, gap_at=4.7)
        chunk, carry = split_for_flush(buf, SR, THRESHOLD)
        cut = len(chunk) / SR
        self.assertAlmostEqual(cut, 4.7, delta=0.05)
        # A real gap needs no overlap: the two pieces tile the buffer exactly.
        self.assertEqual(len(chunk) + len(carry), len(buf))
        self.assertTrue(np.array_equal(np.concatenate([chunk, carry]), buf))

    def test_no_gap_carries_the_tail_into_the_next_chunk(self):
        """Without a gap the cut breaks a word, so the word must be repeated.

        This is the case that loses a subtitle today: Whisper sees a fragment
        ending mid-word, returns empty or a high no_speech_prob, and the words
        around the cut are gone from both chunks.
        """
        buf = signal(5.0, LOUD)
        chunk, carry = split_for_flush(buf, SR, THRESHOLD)
        overlap = len(chunk) + len(carry) - len(buf)
        self.assertAlmostEqual(overlap / SR, 0.3, delta=0.01)
        # The overlapping audio is the same samples, so a word split by the cut
        # is present whole at the start of the next chunk.
        self.assertTrue(np.array_equal(chunk[-overlap:], carry[:overlap]))
        self.assertTrue(np.array_equal(carry[-1:], buf[-1:]))

    def test_quietest_block_wins_even_when_it_is_not_silent(self):
        """Crowd noise never drops below the threshold; the dip is still the best cut."""
        buf = signal(5.0, LOUD)
        dip = int(4.6 * SR)
        buf[dip:dip + int(0.05 * SR)] = signal(0.05, THRESHOLD * 1.5)
        chunk, carry = split_for_flush(buf, SR, THRESHOLD)
        self.assertAlmostEqual(len(chunk) / SR, 4.6, delta=0.05)
        self.assertGreater(len(chunk) + len(carry), len(buf))  # still overlapped

    def test_a_gap_outside_the_search_window_is_ignored(self):
        """Cutting at a gap 2 s back would throw away 2 s of speech, not save it."""
        buf = speech_with_gap(total=5.0, gap_at=2.0)
        chunk, _ = split_for_flush(buf, SR, THRESHOLD)
        self.assertGreater(len(chunk) / SR, 4.3)

    def test_carry_never_exceeds_a_third_of_the_buffer(self):
        """The carry-over is re-transcribed, so it is a tax on the flush rate.

        --max-speech is user-supplied. With fixed 0.6 s / 0.3 s windows against
        a 1.0 s buffer, 0.75 s of every buffer was carried over: 0.25 s of new
        audio per flush, four Whisper calls per second of audio, and an
        audio_queue that grows without bound. A third of the buffer caps the
        cost at 1.5x the flush rate of a naive cut, whatever --max-speech is.
        """
        for max_speech in (0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.5, 5.0):
            with self.subTest(max_speech=max_speech):
                buf = signal(max_speech, LOUD)
                chunk, carry = split_for_flush(buf, SR, THRESHOLD)
                self.assertLessEqual(len(carry), len(buf) / 3)
                # ... and the chunk keeps the rest, so it never drops below
                # min_speech at any --max-speech the CLI accepts.
                self.assertGreaterEqual(len(chunk), len(buf) * 2 / 3)

    def test_flush_rate_stays_near_the_naive_one(self):
        """New audio per flush, which is what decides whether Whisper keeps up."""
        for max_speech in (0.5, 1.0, 1.5, 5.0):
            with self.subTest(max_speech=max_speech):
                buf = signal(max_speech, LOUD)
                _, carry = split_for_flush(buf, SR, THRESHOLD)
                new_audio = (len(buf) - len(carry)) / SR
                self.assertGreaterEqual(new_audio, max_speech * 2 / 3)

    def test_buffer_too_short_to_choose_is_flushed_whole(self):
        buf = signal(0.06, LOUD)
        chunk, carry = split_for_flush(buf, SR, THRESHOLD)
        self.assertTrue(np.array_equal(chunk, buf))
        self.assertLess(len(carry), len(buf))

    def test_empty_buffer(self):
        chunk, carry = split_for_flush(np.zeros(0, dtype=np.float32), SR, THRESHOLD)
        self.assertEqual(len(chunk), 0)
        self.assertEqual(len(carry), 0)

    def test_pieces_are_copies_not_views(self):
        """The callback keeps writing into its buffer; a view would mutate a queued chunk."""
        buf = signal(5.0, LOUD)
        chunk, carry = split_for_flush(buf, SR, THRESHOLD)
        self.assertFalse(np.shares_memory(chunk, buf))
        self.assertFalse(np.shares_memory(carry, buf))


if __name__ == "__main__":
    unittest.main()
