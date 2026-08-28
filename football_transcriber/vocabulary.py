"""Football-specific vocabulary: Whisper prompt hints + post-transcription corrections.

Two complementary mechanisms:

1. ``Vocabulary.prompt`` — an ``initial_prompt`` for Whisper. Giving the model a
   few domain terms (and the players on the pitch) measurably improves how it
   spells them.
2. ``Vocabulary.correct(text)`` — regex normalisation of common mis-hearings
   ("off side" → "offside") plus fuzzy matching of capitalised words against
   the player list ("Harland" → "Haaland", "Sala" → "Salah").
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from pathlib import Path

FOOTBALL_TERMS_EN = [
    "offside", "onside", "through ball", "hat-trick", "free kick", "penalty",
    "corner kick", "goalkeeper", "midfielder", "striker", "VAR", "clean sheet",
    "counter-attack", "stoppage time", "own goal", "Premier League",
]

FOOTBALL_TERMS_JA = [
    "オフサイド", "スルーパス", "ハットトリック", "フリーキック", "PK", "コーナーキック",
    "ゴールキーパー", "ミッドフィルダー", "ストライカー", "VAR", "アディショナルタイム",
]

# (pattern, replacement). Replacement keeps the capitalisation of the first
# character of the match, so "Off side" at a sentence start stays "Offside".
_CORRECTIONS_EN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\boff[\s-]+side\b", re.I), "offside"),
    (re.compile(r"\bon[\s-]+side\b", re.I), "onside"),
    (re.compile(r"\bhat[\s]+trick\b", re.I), "hat-trick"),
    (re.compile(r"\bfree[\s-]*kick(s?)\b", re.I), r"free kick\1"),
    (re.compile(r"\bgoal[\s-]+keeper(s?)\b", re.I), r"goalkeeper\1"),
    (re.compile(r"\bmid[\s-]+fielder(s?)\b", re.I), r"midfielder\1"),
    (re.compile(r"\bcounter[\s]+attack(s?)\b", re.I), r"counter-attack\1"),
    (re.compile(r"\bthrough[\s-]*ball(s?)\b", re.I), r"through ball\1"),
    (re.compile(r"\bstoppage[\s-]*time\b", re.I), "stoppage time"),
    (re.compile(r"\bV\.A\.R\.?", re.I), "VAR"),
    (re.compile(r"\bpremier league\b", re.I), "Premier League"),
    (re.compile(r"\bchampions league\b", re.I), "Champions League"),
]

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]*")


def _keep_case(match: re.Match[str], replacement: str) -> str:
    out = match.expand(replacement)
    if match.group(0)[:1].isupper() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def load_players_file(path: str | Path) -> list[str]:
    """Read one player name per line; blank lines and '#' comments are ignored."""
    names: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                names.append(line)
    return names


class Vocabulary:
    def __init__(
        self,
        language: str = "en",
        players: Iterable[str] = (),
        enabled: bool = True,
        name_cutoff: float = 0.8,
    ):
        self.language = language
        self.enabled = enabled
        self.players = [p.strip() for p in players if p and p.strip()]
        self.name_cutoff = name_cutoff
        # Pre-split player names into lowercase tokens for window matching
        self._player_tokens = [(p, [t.lower() for t in p.split()]) for p in self.players]
        self._by_len: dict[int, list[tuple[str, str]]] = {}
        for canonical, toks in self._player_tokens:
            self._by_len.setdefault(len(toks), []).append((canonical, " ".join(toks)))

    # ------------------------------------------------------------------
    @property
    def prompt(self) -> str | None:
        """Text to pass as Whisper's ``initial_prompt`` (None when disabled)."""
        if not self.enabled:
            return None
        if self.language == "ja":
            parts = ["サッカー実況。用語: " + "、".join(FOOTBALL_TERMS_JA) + "。"]
            if self.players:
                parts.append("選手: " + "、".join(self.players) + "。")
        else:
            parts = ["Football commentary. Terms: " + ", ".join(FOOTBALL_TERMS_EN) + "."]
            if self.players:
                parts.append("Players: " + ", ".join(self.players) + ".")
        return " ".join(parts)

    # ------------------------------------------------------------------
    def correct(self, text: str) -> str:
        if not self.enabled or not text:
            return text
        if self.language == "en":
            for pattern, repl in _CORRECTIONS_EN:
                text = pattern.sub(lambda m, r=repl: _keep_case(m, r), text)
        if self.players:
            text = self._correct_names(text)
        return text

    def _correct_names(self, text: str) -> str:
        tokens = list(_WORD_RE.finditer(text))
        if not tokens:
            return text
        edits: list[tuple[int, int, str]] = []  # (start, end, replacement)
        i = 0
        while i < len(tokens):
            matched = False
            for n in sorted(self._by_len, reverse=True):  # longest names first
                if i + n > len(tokens):
                    continue
                window = tokens[i:i + n]
                # Only consider phrases starting with a capitalised word: Whisper
                # capitalises names, and this keeps common lowercase words from
                # being "corrected" ("salad" must not become "Salah").
                if not window[0].group(0)[0].isupper():
                    continue
                phrase = " ".join(t.group(0).lower() for t in window)
                if sum(len(t.group(0)) for t in window) < 4:
                    continue
                candidates = self._by_len[n]
                exact = next((c for c, low in candidates if low == phrase), None)
                if exact is None:
                    close = difflib.get_close_matches(
                        phrase, [low for _, low in candidates], n=1, cutoff=self.name_cutoff
                    )
                    if close:
                        exact = next(c for c, low in candidates if low == close[0])
                if exact is not None:
                    if exact != " ".join(t.group(0) for t in window):
                        edits.append((window[0].start(), window[-1].end(), exact))
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        for start, end, repl in reversed(edits):
            text = text[:start] + repl + text[end:]
        return text
