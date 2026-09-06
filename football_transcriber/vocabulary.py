"""Football-specific vocabulary: Whisper prompt hints + post-transcription corrections.

Three complementary mechanisms:

1. ``Vocabulary.prompt`` — an ``initial_prompt`` for Whisper. Giving the model a
   few domain terms (and the players on the pitch) measurably improves how it
   spells them.
2. ``Vocabulary.correct(text)`` — regex normalisation of common mis-hearings
   ("off side" → "offside") plus fuzzy matching of capitalised words against
   the player list ("Harland" → "Haaland", "Sala" → "Salah").
3. Explicit aliases — ``"Bukayo Saka=Saka|Sacker|Sarker"``. Fuzzy matching only
   fires above ``name_cutoff``, which surname-only mis-hearings often miss
   ("Sacker" scores 0.6 against "Saka"). Aliases are matched exactly instead, so
   they always win, and they never enter the prompt (they are wrong spellings).

Alias syntax, accepted in ``--players`` and in a ``--players-file`` line::

    Bukayo Saka=Saka|Sacker|Sarker      # canonical=alias|alias|...
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

# Minimum alphabetic length for a *fuzzy* name match. Exact matches (canonical
# names and aliases) bypass it, so a short alias like "Eze" still works.
_MIN_FUZZY_CHARS = 4


def _keep_case(match: re.Match[str], replacement: str) -> str:
    out = match.expand(replacement)
    if match.group(0)[:1].isupper() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def parse_player_spec(spec: str) -> tuple[str, list[str]]:
    """Split ``"Bukayo Saka=Saka|Sacker"`` into ``("Bukayo Saka", ["Saka", "Sacker"])``.

    A spec without ``=`` is just a canonical name with no aliases.
    """
    canonical, _, alias_part = spec.partition("=")
    canonical = canonical.strip()
    aliases = [a.strip() for a in alias_part.split("|")] if alias_part else []
    return canonical, [a for a in aliases if a]


def load_players_file(path: str | Path) -> list[str]:
    """Read one player spec per line; blank lines and '#' comments are ignored.

    Lines may use the alias syntax (``Canonical=alias|alias``); parsing them is
    left to :class:`Vocabulary` so the raw spec survives into the config file.
    """
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
        self.name_cutoff = name_cutoff

        # Canonical names only — these are what the prompt and the output use.
        self.players: list[str] = []
        # canonical -> aliases, kept for --show-config / debugging
        self.aliases: dict[str, list[str]] = {}
        # token count -> {lowercase phrase: canonical}. Holds canonical names and
        # aliases alike; an alias may have a different token count than its name
        # ("Saka" is 1 token, "Bukayo Saka" is 2), so each is keyed by its own.
        self._by_len: dict[int, dict[str, str]] = {}

        for spec in players:
            if not spec or not spec.strip():
                continue
            canonical, aliases = parse_player_spec(spec)
            if not canonical:
                continue
            self.players.append(canonical)
            if aliases:
                self.aliases[canonical] = aliases
            for phrase in (canonical, *aliases):
                toks = phrase.lower().split()
                if toks:
                    self._by_len.setdefault(len(toks), {}).setdefault(" ".join(toks), canonical)

        # Fuzzy candidates per token count (same phrases, list form for difflib)
        self._fuzzy: dict[int, list[str]] = {n: list(d) for n, d in self._by_len.items()}

    # ------------------------------------------------------------------
    @property
    def prompt(self) -> str | None:
        """Text to pass as Whisper's ``initial_prompt`` (None when disabled).

        Only canonical names go in — aliases are mis-spellings, and feeding them
        to the model would encourage exactly the output we are trying to fix.
        """
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
        if self._by_len:
            text = self._correct_names(text)
        return text

    def _match_window(self, window: list[re.Match[str]], n: int) -> str | None:
        """Canonical name for this token window, or None."""
        phrase = " ".join(t.group(0).lower() for t in window)
        candidates = self._by_len[n]
        # Exact first: aliases and canonical names always win, at any length.
        canonical = candidates.get(phrase)
        if canonical is not None:
            return canonical
        # Then fuzzy, which needs enough characters to be worth guessing at.
        if sum(len(t.group(0)) for t in window) < _MIN_FUZZY_CHARS:
            return None
        close = difflib.get_close_matches(phrase, self._fuzzy[n], n=1, cutoff=self.name_cutoff)
        return candidates[close[0]] if close else None

    @staticmethod
    def _fit_replacement(
        canonical: str, tokens: list[re.Match[str]], i: int, n: int
    ) -> tuple[int, str]:
        """Decide what to write, and from which token, for a match at ``tokens[i:i+n]``.

        A surname-only alias ("Havits") carries the full canonical name ("Kai
        Havertz"), so writing it verbatim would duplicate a first name that is
        already in the text ("Kai Kai Havertz"). Two rules avoid that:

        - if the tokens just before the window already spell the start of the
          name, absorb them and write the full name ("Kai Havits" → "Kai Havertz");
        - otherwise write only the trailing part of the name, so we never invent
          a first name the commentator did not say ("Ezra Konser" → "Ezra Konsa").
        """
        ctoks = canonical.split()
        lead = len(ctoks) - n
        start = i
        replacement = canonical
        if lead > 0:
            before = [t.group(0).lower() for t in tokens[max(0, i - lead):i]]
            if i - lead >= 0 and before == [c.lower() for c in ctoks[:lead]]:
                start = i - lead                      # absorb the first name(s)
            else:
                replacement = " ".join(ctoks[-n:])    # trailing part only
        # Guard against repeating a word that is already there, which happens when
        # an alias spells part of a name ("Myles" + alias "Lewis Skelly").
        rtoks = replacement.split()
        while start > 0 and rtoks and tokens[start - 1].group(0).lower() == rtoks[0].lower():
            start -= 1
        return start, replacement

    def _correct_names(self, text: str) -> str:
        tokens = list(_WORD_RE.finditer(text))
        if not tokens:
            return text
        edits: list[tuple[int, int, str]] = []  # (start, end, replacement)
        i = 0
        while i < len(tokens):
            matched = False
            for n in sorted(self._by_len, reverse=True):  # longest phrases first
                if i + n > len(tokens):
                    continue
                window = tokens[i:i + n]
                # Only consider phrases starting with a capitalised word: Whisper
                # capitalises names, and this keeps common lowercase words from
                # being "corrected" ("salad" must not become "Salah").
                if not window[0].group(0)[0].isupper():
                    continue
                canonical = self._match_window(window, n)
                if canonical is not None:
                    first, replacement = self._fit_replacement(canonical, tokens, i, n)
                    start, end = tokens[first].start(), window[-1].end()
                    if replacement != text[start:end]:
                        # Absorbing tokens leftwards can swallow an earlier edit
                        while edits and edits[-1][1] > start:
                            edits.pop()
                        edits.append((start, end, replacement))
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        for start, end, repl in reversed(edits):
            text = text[:start] + repl + text[end:]
        return text
