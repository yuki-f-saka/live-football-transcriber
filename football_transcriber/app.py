"""Shared Qt application bootstrap (signal handling, overlay window, text polling)."""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
from typing import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .config import Settings
from .overlay import SubtitleWindow

log = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    """Log to both the terminal and a file for post-crash inspection."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.log_file, encoding="utf-8"),
        ],
    )
    # Our own modules log at DEBUG; third-party libraries (httpx, RealtimeSTT pipes, ...) stay at INFO+
    logging.getLogger("football_transcriber").setLevel(logging.DEBUG)

    # Catch unhandled exceptions in any thread and write them to the log
    def _handle_thread_exception(args):
        logging.getLogger("football_transcriber").critical(
            "Unhandled exception in thread '%s'",
            args.thread.name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _handle_thread_exception


class OverlayApp:
    """Owns the QApplication, the subtitle window and the text queue.

    Transcription backends push ``("final", text)`` / ``("partial", text)``
    tuples onto ``text_queue`` from any thread; a 50 ms Qt timer drains the
    queue on the GUI thread.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.qt_app = QApplication(sys.argv[:1])

        # Handle Ctrl+C gracefully (SIGINT)
        signal.signal(signal.SIGINT, lambda *_: QApplication.quit())
        # Give Python a chance to handle signals inside the C++ Qt event loop
        self._sigint_timer = QTimer()
        self._sigint_timer.start(200)
        self._sigint_timer.timeout.connect(lambda: None)

        self.window = SubtitleWindow(settings)
        self.window.show()
        self.window.raise_()
        if settings.fullscreen_overlay and sys.platform == "darwin":
            from .macos import make_visible_over_fullscreen
            make_visible_over_fullscreen(self.window)

        self.text_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_text)
        self._poll_timer.start(50)

    # -- called from any thread --
    def push_final(self, text: str) -> None:
        self.text_queue.put(("final", text))

    def push_partial(self, text: str) -> None:
        self.text_queue.put(("partial", text))

    def push_status(self, text: str) -> None:
        self.text_queue.put(("status", text))

    # -- GUI thread --
    def _poll_text(self) -> None:
        try:
            while True:
                kind, text = self.text_queue.get_nowait()
                if kind == "partial":
                    self.window.show_partial(text)
                elif kind == "status":
                    self.window.show_status(text)
                else:
                    self.window.show_text(text)
        except queue.Empty:
            pass

    def attach_gain_control(self, gain_value: float):
        """Create the runtime Gain and (if stdin is a TTY) the keyboard controller.

        Gain changes are shown in the overlay, logged, and persisted to the config file.
        """
        from .audio import Gain, KeyboardController

        def on_change(value: float) -> None:
            log.info("Input gain: %.1fx", value)
            self.push_status(gain.label())
            try:
                self.settings.save_key("gain", value)
            except OSError:
                log.exception("Could not persist gain")

        gain = Gain(gain_value, on_change=on_change)
        self.gain = gain
        self.keyboard = None
        if KeyboardController.available():
            self.keyboard = KeyboardController(gain, on_quit=lambda: os.kill(os.getpid(), signal.SIGINT))
            self.keyboard.start()
            log.info(KeyboardController.HELP)
        else:
            log.info("stdin is not a TTY — keyboard gain control disabled (use --gain)")
        if gain.value != 1.0:
            self.push_status(gain.label())
        return gain

    def exec(self, on_exit: Callable[[], None] | None = None) -> int:
        try:
            return self.qt_app.exec()
        except KeyboardInterrupt:
            return 0
        finally:
            if on_exit:
                on_exit()
            kb = getattr(self, "keyboard", None)
            if kb is not None:
                kb.stop()
                kb.join(timeout=1)
