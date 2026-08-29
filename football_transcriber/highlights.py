"""Detect key match moments from transcript keywords and trigger actions (issue #14).

Every finalized transcript is matched against per-event regexes. When an event
fires (subject to a per-event cooldown so "GOAL! GOAL! GOAL!" counts once) the
configured actions run: append a timestamped marker to a log file (for later
video clipping), post a macOS notification, and/or play a sound.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path

log = logging.getLogger(__name__)

# event name → regex (English + Japanese). Order matters only for display.
EVENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "goal": re.compile(
        r"\b(goal(?!\s*(kick|keeper))s?|scores|scored|equali[sz]er|hat-?trick|back of the net|"
        r"into the net|it's in)\b|\b\d{1,2}\s*-\s*\d{1,2}\b|ゴール|得点|ハットトリック|同点",
        re.I,
    ),
    "penalty": re.compile(r"\bpenalt(y|ies)\b|\bspot[\s-]kick\b|PK|ペナルティ", re.I),
    "red_card": re.compile(r"\bred card\b|\bsent off\b|\bsending off\b|\bdismiss(ed|al)\b|レッドカード|退場", re.I),
    "yellow_card": re.compile(r"\byellow card\b|\bbooked\b|\bbooking\b|\bcaution(ed)?\b|イエローカード|警告", re.I),
    "var": re.compile(r"\bVAR\b|\bvideo (assistant|review)\b|ビデオ判定", re.I),
    "offside": re.compile(r"\boffside\b|オフサイド", re.I),
    "free_kick": re.compile(r"\bfree[\s-]kick\b|フリーキック", re.I),
    "corner": re.compile(r"\bcorner( kick)?\b|コーナー(キック)?", re.I),
    "substitution": re.compile(r"\bsubstitut(e|ion)\b|\bcomes on\b|\bcoming on\b|交代", re.I),
}

DEFAULT_EVENTS = ["goal", "penalty", "red_card", "var"]
EVENT_LABELS = {
    "goal": "⚽ GOAL", "penalty": "🎯 PENALTY", "red_card": "🟥 RED CARD", "yellow_card": "🟨 YELLOW CARD",
    "var": "📺 VAR", "offside": "🚩 OFFSIDE", "free_kick": "🦶 FREE KICK", "corner": "🚩 CORNER",
    "substitution": "🔁 SUB",
}


def parse_event_list(value: str | Iterable[str] | None) -> list[str]:
    """'goal,penalty' / 'all' / list → validated list of event names."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    out: list[str] = []
    for item in items:
        for name in str(item).split(","):
            name = name.strip().lower().replace("-", "_").replace(" ", "_")
            if not name:
                continue
            if name == "all":
                out.extend(EVENT_PATTERNS)
            elif name in EVENT_PATTERNS:
                out.append(name)
            else:
                raise ValueError(f"unknown highlight event '{name}'. Choose from: {', '.join(EVENT_PATTERNS)}, all")
    seen: set[str] = set()
    return [e for e in out if not (e in seen or seen.add(e))]


class HighlightDetector:
    def __init__(
        self,
        events: Iterable[str] = DEFAULT_EVENTS,
        cooldown: float = 10.0,
        log_path: str | Path | None = None,
        notify: bool = False,
        sound: str | Path | None = None,
        on_event: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.events = list(events)
        self.cooldown = cooldown
        self.log_path = Path(log_path) if log_path else None
        self.notify = notify
        self.sound = str(sound) if sound else None
        self.on_event = on_event
        self._clock = clock
        self._started = clock()
        self._last_fired: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.events)

    # ------------------------------------------------------------------
    def detect(self, text: str) -> list[str]:
        """Return event names whose pattern matches ``text`` (no cooldown, no side effects)."""
        return [e for e in self.events if EVENT_PATTERNS[e].search(text)]

    def handle(self, text: str) -> list[str]:
        """Detect events, apply cooldown, run actions. Returns the events that fired."""
        if not self.events:
            return []
        now = self._clock()
        fired: list[str] = []
        for event in self.detect(text):
            last = self._last_fired.get(event)
            if last is not None and now - last < self.cooldown:
                continue
            self._last_fired[event] = now
            fired.append(event)
            self._run_actions(event, text, now)
        return fired

    # ------------------------------------------------------------------
    def _run_actions(self, event: str, text: str, now: float) -> None:
        label = EVENT_LABELS.get(event, event.upper())
        elapsed = int(now - self._started)
        marker = f"[{time.strftime('%H:%M:%S')}] (+{elapsed // 60:02d}:{elapsed % 60:02d}) {label}: {text}"
        log.info("HIGHLIGHT %s", marker)
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(marker + "\n")
            except OSError:
                log.exception("Could not write highlight marker")
        if self.notify:
            _notify(label, text)
        if self.sound:
            _play_sound(self.sound)
        if self.on_event:
            try:
                self.on_event(event, text)
            except Exception:
                log.exception("Highlight callback failed")


def _osascript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _notify(title: str, body: str) -> None:
    """macOS notification via osascript (non-blocking)."""
    script = f'display notification "{_osascript_escape(body[:200])}" with title "{_osascript_escape(title)}"'
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.exception("osascript not available")


def _play_sound(path: str) -> None:
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        log.exception("afplay not available")
