"""Post-transcription text filters (hallucination detection)."""

from __future__ import annotations

import re

# ``\w`` is Unicode-aware, which matters: an explicit ``a-z`` class turns every
# accented letter into a separator, so "Darwin Núñez, Luis Díaz" would normalise
# to six tokens ("darwin n ez luis d az") and trip the run threshold below while
# being perfectly ordinary commentary.
_NON_WORD_RE = re.compile(r"[\W_]+")
_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")

def _normalise(text: str) -> str:
    return _NON_WORD_RE.sub(" ", text.lower()).strip()


# A cycle has to be this long before periodicity means anything: "banana" and
# "Nou! Nou!" are periodic too, and short strings hit a cycle by accident.
_MIN_CYCLE_CHARS = 16
# Japanese fits a whole sentence into 16 characters, so the same threshold would
# exempt every realistic CJK loop ("ゴール" x4 is 12 characters).
_MIN_CYCLE_CHARS_CJK = 8
# A long repeating unit is a hallucination at four cycles. A *short* one is a
# chant a commentator actually produces — "Come on, come on, come on, come on!"
# is a 6-character unit repeated four times — so a short unit has to repeat
# more often before we believe it. Every one of the nine repetitions in the
# 4854-line reference log clears the higher bar (5 to 111 cycles).
_MIN_CYCLES = 4
_MIN_CYCLES_SHORT_UNIT = 6
_SHORT_UNIT_CHARS = 10

# Phrases Whisper emits from its training data (video sign-offs, subtitle
# credits) when it is fed noise. They are not repetitive and not prompt echoes,
# so nothing else catches them. The cost of the list is that a commentator
# signing off at full time ("thanks for watching") loses that one subtitle —
# cheaper than the alternative, which is boilerplate appearing over live play.
_BOILERPLATE = (
    "thanks for watching", "thank you for watching", "thanks for listening",
    # "see you in the next" alone would also drop "see you in the next few
    # minutes after the break" and "see you in the next round" — mid-match
    # phrases, not sign-offs. Only the video-specific form is boilerplate.
    "see you next time", "see you in the next video", "please subscribe",
    "like and subscribe", "subscribe to the channel", "subtitles by",
    "subtitled by", "transcription by", "amara org",
    "ご視聴ありがとう", "チャンネル登録", "最後までご視聴",
)


def is_hallucination(text: str, min_alpha_chars: int = 4) -> bool:
    """Detect Whisper hallucinations: symbol-only output, repetition, boilerplate.

    - Fewer than ``min_alpha_chars`` alphabetic characters (e.g. "...", "!", "St-")
    - The same word repeated 4+ times consecutively ("far far far far")
    - Any unit repeated 4+ times without a space at the cycle boundary
      ("Would it beWould it beWould it be...") — see :func:`_is_cyclic`
    - Known Whisper training-data boilerplate ("we'll see you next time")
    """
    alpha_chars = sum(c.isalpha() for c in text)
    if alpha_chars < min_alpha_chars:
        return True
    words = text.split()
    if any(len(set(words[i:i + 4])) == 1 for i in range(len(words) - 3)):
        return True
    return _is_cyclic(text) or _is_boilerplate(text)


def _is_cyclic(text: str) -> bool:
    """True when the text is a short unit repeated ``_MIN_CYCLES`` times or more.

    The word-level check above cannot see this. Whisper emits its repetitions
    with no separator between cycles ("Would it beWould it be..."), so
    ``split()`` yields ["Would", "it", "beWould", "it", "beWould", ...] and no
    four consecutive tokens are ever equal. The repeating unit is also a
    *phrase*, not a word. Comparing characters answers both: spaces are removed
    first, so a cycle boundary can fall anywhere.

    The shortest period comes from the KMP prefix function; a partial final
    cycle ("abcabcabcab") still counts, because that is what a chunk cut in the
    middle of a hallucination looks like. How many cycles are needed depends on
    the size of the unit: four for a phrase, six for a unit under
    ``_SHORT_UNIT_CHARS``, which is the length of a chant.
    """
    s = _normalise(text).replace(" ", "")
    n = len(s)
    if n < (_MIN_CYCLE_CHARS_CJK if _CJK_RE.search(s) else _MIN_CYCLE_CHARS):
        return False
    pi = [0] * n
    k = 0
    for i in range(1, n):
        while k and s[i] != s[k]:
            k = pi[k - 1]
        if s[i] == s[k]:
            k += 1
        pi[i] = k
    period = n - pi[n - 1]
    if period >= n:
        return False
    needed = _MIN_CYCLES if period >= _SHORT_UNIT_CHARS else _MIN_CYCLES_SHORT_UNIT
    return n // period >= needed


def _is_boilerplate(text: str) -> bool:
    t = _normalise(text)
    return any(phrase in t for phrase in _BOILERPLATE)


# An echo is a *run* of prompt text, not any phrase that happens to occur in it.
# The prompt is a list of football terms and player names, so "free kick",
# "own goal" and "Declan Rice" are prompt substrings *and* real commentary;
# parroting spills several list items at once. Requiring a long run keeps the
# real speech. The cost is that a very short echo ("Football commentary.") may
# slip through — one stray subtitle is cheaper than dropping every "Free kick."
# That stray subtitle also reaches highlights.handle(), so a short echo like
# "penalty, corner kick." can fire an event. Gating highlights on "is a prompt
# substring" would be worse: penalty, corner kick, own goal and VAR are all
# prompt terms *and* real events, so it would suppress most true positives.
# The per-event cooldown limits the damage to one marker per event per window.
_MIN_ECHO_WORDS = 5
# Japanese has no spaces, so a run of terms collapses into few tokens and is
# measured in characters instead.
_MIN_ECHO_CHARS = 12


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
