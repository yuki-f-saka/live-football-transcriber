"""Post-transcription text filters (hallucination detection)."""

from __future__ import annotations


def is_hallucination(text: str, min_alpha_chars: int = 4) -> bool:
    """Detect Whisper hallucinations: symbol-only output or repeated words.

    - Fewer than ``min_alpha_chars`` alphabetic characters (e.g. "...", "!", "St-")
    - The same word repeated 4+ times consecutively ("far far far far")
    """
    alpha_chars = sum(c.isalpha() for c in text)
    if alpha_chars < min_alpha_chars:
        return True
    words = text.split()
    for i in range(len(words) - 3):
        if len(set(words[i:i + 4])) == 1:
            return True
    return False
