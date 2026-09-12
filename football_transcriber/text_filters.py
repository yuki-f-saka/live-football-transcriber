"""Post-transcription text filters (hallucination detection)."""

from __future__ import annotations

import re


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


_NON_WORD_RE = re.compile(r"[^0-9a-z぀-ヿ一-鿿]+")
_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")

# An echo is a *run* of prompt text, not any phrase that happens to occur in it.
# The prompt is a list of football terms and player names, so "free kick",
# "own goal" and "Declan Rice" are prompt substrings *and* real commentary;
# parroting spills several list items at once. Requiring a long run keeps the
# real speech. The cost is that a very short echo ("Football commentary.") may
# slip through — one stray subtitle is cheaper than dropping every "Free kick."
_MIN_ECHO_WORDS = 5
# Japanese has no spaces, so a run of terms collapses into few tokens and is
# measured in characters instead.
_MIN_ECHO_CHARS = 12


def _normalise(text: str) -> str:
    return _NON_WORD_RE.sub(" ", text.lower()).strip()


def looks_like_prompt_echo(text: str, prompt: str | None) -> bool:
    """True when Whisper just parroted (part of) its ``initial_prompt``.

    A known failure mode: on silence or noise the model emits the prompt text
    instead of a transcription.
    """
    if not prompt:
        return False
    t = _normalise(text)
    if not t or t not in _normalise(prompt):
        return False
    if _CJK_RE.search(t):
        return len(t.replace(" ", "")) >= _MIN_ECHO_CHARS
    return len(t.split()) >= _MIN_ECHO_WORDS
