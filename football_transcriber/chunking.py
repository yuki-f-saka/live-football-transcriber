"""Where to cut a force-flushed speech buffer (issue #30).

Live commentary rarely pauses, so ``post_speech_silence`` — the natural flush —
seldom fires and the ``max_speech`` safety flush becomes the *primary*
segmentation mechanism. Cutting at exactly ``max_speech`` cuts mid-word: Whisper
then sees a fragment that starts and ends in the middle of a word, returns empty
text or a high ``no_speech_prob``, and *both* halves are discarded by the
filters. The longer the sentence, the more fragments it is split into, and the
higher the chance that every one of them is rejected — which is what "a long
sentence produces no subtitle at all" looks like from the outside.

:func:`split_for_flush` makes the cut a decision instead of an accident:

1. cut at the quietest 50 ms block near the end of the buffer, so cuts land in
   the gaps *between* words rather than inside one;
2. when even the quietest block is above ``silence_threshold`` — no gap exists,
   the cut is going to break a word — carry the last ``overlap_seconds`` of
   audio into the next buffer, so the broken word is whole in the next chunk.

This module is deliberately free of audio-device and Qt imports: it is called
from the real-time ``audio_callback`` and must be cheap (a few hundred RMS
values on a 5 s buffer) and unit-testable without hardware.
"""

from __future__ import annotations

import numpy as np

SEARCH_SECONDS = 0.6    # how far back from the end to look for a gap
BLOCK_SECONDS = 0.05    # granularity of the search == the audio callback's block size
OVERLAP_SECONDS = 0.3   # carried into the next buffer when the cut breaks a word


def split_for_flush(
    buffer: np.ndarray,
    sample_rate: int,
    silence_threshold: float,
    search_seconds: float = SEARCH_SECONDS,
    block_seconds: float = BLOCK_SECONDS,
    overlap_seconds: float = OVERLAP_SECONDS,
) -> tuple[np.ndarray, np.ndarray]:
    """Split a force-flushed buffer into ``(chunk_to_transcribe, carry_over)``.

    The carry-over is what the next buffer starts with; it is always strictly
    shorter than ``buffer``, so a small ``--max-speech`` cannot livelock the
    callback into flushing the same audio forever.
    """
    n = len(buffer)
    block = max(1, int(block_seconds * sample_rate))
    # Both windows are capped as a fraction of the buffer: the chunk keeps at
    # least half of it, and the overlap fallback at most a quarter. Together
    # that bounds the carry-over at 3/4 of the buffer for any settings.
    overlap = min(int(overlap_seconds * sample_rate), n // 4)
    search = min(int(search_seconds * sample_rate), n // 2)

    if search < 2 * block:
        # Too short to choose between blocks — cut at the end, and still carry
        # the overlap, because this cut is as likely to be mid-word as any.
        return buffer.copy(), buffer[n - overlap:].copy()

    starts = range(n - (search // block) * block, n - block + 1, block)
    rms = [(float(np.sqrt(np.mean(buffer[s:s + block] ** 2))), s) for s in starts]
    quietest, cut = min(rms)

    chunk = buffer[:cut].copy()
    if quietest < silence_threshold:
        # A real gap: the cut lands between words, so nothing needs repeating.
        return chunk, buffer[cut:].copy()
    return chunk, buffer[cut - overlap:].copy()
