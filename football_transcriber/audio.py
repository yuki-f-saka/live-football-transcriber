"""Audio input helpers shared by both transcription modes."""

from __future__ import annotations

import sounddevice as sd


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) for every device that has input channels."""
    return [
        (i, d["name"])
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def find_device_index(name: str) -> int:
    """Return the index of the first input device whose name contains ``name``."""
    for i, dev_name in list_input_devices():
        if name in dev_name:
            return i
    available = "\n".join(f"  {i}: {n}" for i, n in list_input_devices())
    raise RuntimeError(f"Device '{name}' not found.\nAvailable:\n{available}")


# ----------------------------------------------------------------------
# Runtime input gain (issue #2)
# ----------------------------------------------------------------------

import logging
import os
import select
import sys
import threading
from collections import Counter
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


class Gain:
    """A mutable input-gain multiplier shared between the key handler and the audio thread.

    Reads/writes of a Python float are atomic, so no lock is needed on the
    real-time audio path.
    """

    MIN, MAX, STEP = 0.0, 5.0, 0.1

    def __init__(self, value: float = 1.0, on_change: Callable[[float], None] | None = None):
        self.value = self._clamp(value)
        self._on_change = on_change
        self._pre_mute: float | None = None

    @classmethod
    def _clamp(cls, v: float) -> float:
        return round(min(cls.MAX, max(cls.MIN, v)), 2)

    def set(self, v: float) -> float:
        self.value = self._clamp(v)
        if self._on_change:
            self._on_change(self.value)
        return self.value

    def up(self) -> float:
        return self.set(self.value + self.STEP)

    def down(self) -> float:
        return self.set(self.value - self.STEP)

    def reset(self) -> float:
        return self.set(1.0)

    def toggle_mute(self) -> float:
        if self.value > 0:
            self._pre_mute = self.value
            return self.set(0.0)
        restored = self.set(self._pre_mute or 1.0)
        self._pre_mute = None
        return restored

    def apply(self, audio: np.ndarray) -> np.ndarray:
        """Multiply a float32 block by the gain and clip to [-1, 1]. Real-time safe."""
        g = self.value
        if g == 1.0:
            return audio
        return np.clip(audio * g, -1.0, 1.0)

    def label(self) -> str:
        return "🔇 muted" if self.value == 0 else f"🔊 gain {self.value:.1f}x"


class KeyboardController(threading.Thread):
    """Reads single keypresses from the terminal (cbreak mode) on a background thread.

    Used for runtime control because the overlay window is click-through and
    never receives keyboard focus. Only active when stdin is a TTY.

    Keys: ``+``/``=``/Up = gain up, ``-``/``_``/Down = gain down, ``0`` = reset,
    ``m`` = mute toggle, ``q``/Esc = quit.
    """

    HELP = "Keys: [+]/[-] or Up/Down = gain   [0] = reset   [m] = mute   [q]/Esc = quit"

    def __init__(self, gain: Gain, on_quit: Callable[[], None]):
        super().__init__(name="keyboard", daemon=True)
        self.gain = gain
        self.on_quit = on_quit
        self._stop_event = threading.Event()

    @staticmethod
    def available() -> bool:
        return sys.stdin is not None and sys.stdin.isatty()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)  # keeps ISIG, so Ctrl+C still raises SIGINT
            while not self._stop_event.is_set():
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    continue
                key = os.read(fd, 1)
                if key == b"\x1b":
                    # Escape alone → quit; "\x1b[A"/"\x1b[B" → arrow keys
                    r, _, _ = select.select([fd], [], [], 0.05)
                    seq = os.read(fd, 2) if r else b""
                    if seq == b"[A":
                        key = b"+"
                    elif seq == b"[B":
                        key = b"-"
                    else:
                        key = b"q"
                self._handle(key)
        except Exception:
            log.exception("Keyboard controller stopped")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _handle(self, key: bytes) -> None:
        if key in (b"+", b"="):
            self.gain.up()
        elif key in (b"-", b"_"):
            self.gain.down()
        elif key == b"0":
            self.gain.reset()
        elif key in (b"m", b"M"):
            self.gain.toggle_mute()
        elif key in (b"q", b"Q"):
            self.on_quit()


# ----------------------------------------------------------------------
# Input monitoring (issue #27)
# ----------------------------------------------------------------------


class InputMonitor(threading.Thread):
    """Explains, periodically, why no subtitles are appearing.

    An empty overlay has several causes that look identical in the log: nothing
    routed into the capture device, audio arriving below ``silence_threshold``,
    or chunks transcribed and then rejected by the filters. This thread reports
    which one it is.

    ``note_block`` and ``note_speech`` are called from the real-time audio
    callback, so they only bump a float/int — every log call happens here.
    Pass ``threshold=None`` when the backend does its own VAD (streaming mode),
    which suppresses the "below the speech threshold" branch.
    """

    QUIET = 0.001  # peak RMS below this is indistinguishable from digital silence

    def __init__(
        self,
        device: str,
        threshold: float | None,
        gain: "Gain | None" = None,
        interval: float = 20.0,
        on_warning: Callable[[str], None] | None = None,
        min_speech: float | None = None,
    ):
        super().__init__(name="input_monitor", daemon=True)
        self.device = device
        self.threshold = threshold
        self.gain = gain
        self.interval = interval
        self.min_speech = min_speech
        self.on_warning = on_warning
        self._stop_event = threading.Event()
        self._peak = 0.0
        self._blocks = 0
        self._speech = 0
        self._texts = 0
        self._rejects: Counter[str] = Counter()

    # -- real-time audio thread: no allocation, no I/O --
    def note_block(self, rms: float) -> None:
        if rms > self._peak:
            self._peak = rms
        self._blocks += 1

    def note_speech(self) -> None:
        self._speech += 1

    # -- transcription thread --
    def note_text(self) -> None:
        self._texts += 1

    def note_reject(self, reason: str) -> None:
        self._rejects[reason] += 1

    # -- monitor thread --
    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._report()
            except Exception:
                log.exception("Input monitor failed")

    def _report(self) -> None:
        peak, blocks = self._peak, self._blocks
        speech, texts, rejects = self._speech, self._texts, self._rejects
        self._peak = 0.0
        self._blocks = self._speech = self._texts = 0
        self._rejects = Counter()
        if texts:
            return  # subtitles are appearing; nothing to explain
        message, badge = self._diagnose(peak, blocks, speech, rejects)
        log.warning("%s", message)
        if self.on_warning:
            self.on_warning(badge)

    def _diagnose(self, peak: float, blocks: int, speech: int, rejects: "Counter[str]") -> tuple[str, str]:
        """Pick the one explanation the window's numbers actually support.

        Order matters, and so does each guard: a branch must never print figures
        that contradict the sentence around it. ``speech`` in particular is only
        counted by the vad backend, and only when a chunk is *queued*, so it is
        not a usable proxy for "was there any speech".
        """
        secs = self.interval
        gain = f", gain {self.gain.value:.1f}x" if self.gain else ""
        if self.gain is not None and self.gain.value == 0:
            return (
                f"Input is muted (gain 0), so nothing reaches the transcriber. "
                f"Press 'm' to unmute, or pass --gain.",
                "🔇 muted",
            )
        if blocks == 0:
            return (
                f"No audio delivered by '{self.device}' in the last {secs:.0f}s — "
                f"the capture stream is not running yet, or it is open and idle.",
                "⚠ no audio",
            )
        if peak < self.QUIET:
            return (
                f"Silence on '{self.device}' for {secs:.0f}s (peak RMS {peak:.4f}{gain}). "
                f"Check that the system output is a Multi-Output device that includes it, "
                f"and that the source is actually playing.",
                "⚠ no audio",
            )
        if rejects:
            # Do not report a chunk count here: the rejected chunk may have been
            # queued in the previous window, and streaming mode never counts one.
            detail = ", ".join(f"{reason}={n}" for reason, n in sorted(rejects.items()))
            return (
                f"Every transcription in the last {secs:.0f}s was filtered out "
                f"({detail}). Run with --log-file and read the DEBUG lines to see the discarded text.",
                "⚠ all filtered",
            )
        if self.threshold is not None and peak <= self.threshold:
            return (
                f"Audio on '{self.device}' stayed below the speech threshold for {secs:.0f}s "
                f"(peak RMS {peak:.4f} < {self.threshold:.3f}{gain}). "
                f"Lower --threshold or raise the gain with '+'.",
                f"⚠ quiet {peak:.3f}<{self.threshold:.2f}",
            )
        if self.threshold is not None and speech == 0:
            # Loud enough, but nothing was ever long enough to be worth sending.
            too_short = f" shorter than --min-speech {self.min_speech:g}s" if self.min_speech else " too short"
            return (
                f"Audio on '{self.device}' crossed the speech threshold "
                f"(peak RMS {peak:.4f} > {self.threshold:.3f}{gain}) but every utterance was"
                f"{too_short}, so nothing was sent for transcription.",
                "⚠ too short",
            )
        if self.threshold is None:
            # Streaming mode: Silero owns the VAD, so we know the level and nothing else.
            return (
                f"Audio on '{self.device}' (peak RMS {peak:.4f}{gain}) produced no text in "
                f"{secs:.0f}s — the backend found no speech in it, or the models are still loading.",
                "⚠ no text",
            )
        return (
            f"{speech} chunk(s) sent for transcription in {secs:.0f}s but no text came back "
            f"(peak RMS {peak:.4f}{gain}).",
            "⚠ no text",
        )
