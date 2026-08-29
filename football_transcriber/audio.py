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
