#!/usr/bin/env python3
"""
Real-time streaming transcription overlay using RealtimeSTT.

Displays partial (in-progress) text while speaking, then overwrites
with the finalized transcript from the small.en model when the
utterance ends.

Partial text: white, updated live (tiny.en for speed)
Final text:   white, auto-clears after SUBTITLE_SECONDS (small.en for accuracy)

Usage:
    python overlay_streaming.py

Quit: press Escape, or Ctrl+C in terminal.
"""

import queue
import signal
import sys
import threading
import time
from RealtimeSTT import AudioToTextRecorder
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# --- Audio / Model settings ---
DEVICE_NAME          = "BlackHole 2ch"
FINAL_MODEL          = "small.en"    # high-accuracy model for finalized transcription
REALTIME_MODEL       = "tiny.en"     # fast model for real-time partial updates

# --- Overlay appearance ---
FONT_SIZE            = 30
FONT_COLOR_FINAL     = "white"       # finalized text
FONT_COLOR_PARTIAL   = "white"       # in-progress text
MAX_PARTIAL_CHARS    = 80            # max characters shown for partial text (prevents overflow during long speech)
BG_COLOR             = "#111111"
BG_OPACITY           = 200
SUBTITLE_SECONDS     = 4.0
SCREEN_MARGIN_Y      = 40
WINDOW_WIDTH_RATIO   = 0.65
SCREEN_INDEX         = 1

# ------------------------------

def find_input_device_index(name: str) -> int:
    import pyaudio
    pa = pyaudio.PyAudio()
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if name in info["name"] and info["maxInputChannels"] > 0:
            pa.terminate()
            return i
    pa.terminate()
    available = []
    pa2 = pyaudio.PyAudio()
    for i in range(pa2.get_device_count()):
        info = pa2.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            available.append(f"  {i}: {info['name']}")
    pa2.terminate()
    raise RuntimeError(f"Device '{name}' not found.\nAvailable:\n" + "\n".join(available))


class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint        # no title bar
            | Qt.WindowType.WindowStaysOnTopHint     # always on top
            | Qt.WindowType.WindowTransparentForInput  # click-through
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # don't steal focus

        # Position window on the target screen
        screens = QApplication.screens()
        target = screens[SCREEN_INDEX] if SCREEN_INDEX < len(screens) else screens[0]
        if SCREEN_INDEX >= len(screens):
            print(f"[warn] SCREEN_INDEX={SCREEN_INDEX} not found. Using screen 0.")
        print(f"Using screen [{SCREEN_INDEX if SCREEN_INDEX < len(screens) else 0}]: {target.name()}")
        screen = target.availableGeometry()
        win_w = int(screen.width() * WINDOW_WIDTH_RATIO)
        win_h = 90
        x = screen.x() + (screen.width() - win_w) // 2
        y = screen.y() + SCREEN_MARGIN_Y
        self.setGeometry(x, y, win_w, win_h)
        print(f"Overlay window: {win_w}x{win_h} at ({x}, {y})")

        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFont(QFont("Helvetica", FONT_SIZE, QFont.Weight.Bold))
        self.label.setGeometry(0, 0, win_w, win_h)

        color = QColor(BG_COLOR)
        self._bg_rgba = f"rgba({color.red()}, {color.green()}, {color.blue()}, {BG_OPACITY})"
        self._set_style(FONT_COLOR_FINAL)

        # Timer to auto-clear subtitle after finalization
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear)

    def _set_style(self, font_color: str):
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {font_color};
                background-color: {self._bg_rgba};
                border-radius: 8px;
                padding: 6px 14px;
            }}
        """)

    def show_partial(self, text: str):
        """Show in-progress text — does not start the auto-clear timer."""
        self._clear_timer.stop()
        self._set_style(FONT_COLOR_PARTIAL)
        self.label.setText(text)

    def show_final(self, text: str):
        """Show finalized text and start the auto-clear timer."""
        self._set_style(FONT_COLOR_FINAL)
        self.label.setText(text)
        self._clear_timer.start(int(SUBTITLE_SECONDS * 1000))

    def _clear(self):
        self.label.setText("")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()


def main():
    device_index = find_input_device_index(DEVICE_NAME)
    print(f"Input device [{device_index}]: {DEVICE_NAME}")
    print(f"Final model: {FINAL_MODEL}  |  Realtime model: {REALTIME_MODEL}")
    print("Listening... (Escape or Ctrl+C to quit)\n")

    app = QApplication(sys.argv)

    # Handle Ctrl+C gracefully (SIGINT)
    signal.signal(signal.SIGINT, lambda *_: QApplication.quit())
    # Give Python a chance to handle signals inside the C++ Qt event loop
    sigint_timer = QTimer()
    sigint_timer.start(200)
    sigint_timer.timeout.connect(lambda: None)

    window = SubtitleWindow()
    window.show()
    window.raise_()
    window.show_partial("▶ Overlay active — loading models...")

    # Queue for passing text to the Qt main thread safely
    # Items are ("partial", text) or ("final", text) tuples
    text_queue: queue.Queue = queue.Queue()

    def on_partial(text: str):
        text = text.strip()
        if text:
            # Show only the trailing N characters to prevent overflow during long speech
            text_queue.put(("partial", text[-MAX_PARTIAL_CHARS:]))

    print("Loading models (this may take a moment on first run)...")
    recorder = AudioToTextRecorder(
        model=FINAL_MODEL,
        realtime_model_type=REALTIME_MODEL,
        language="en",
        input_device_index=device_index,
        device="cpu",                          # no CUDA on Mac; use cpu
        compute_type="int8",
        enable_realtime_transcription=True,
        use_main_model_for_realtime=False,     # tiny.en for partial, small.en for final
        realtime_processing_pause=0.1,
        init_realtime_after_seconds=0.2,
        on_realtime_transcription_update=on_partial,
        silero_sensitivity=0.4,
        post_speech_silence_duration=0.4,
        min_length_of_recording=0.3,
        beam_size=1,
        beam_size_realtime=1,
        spinner=False,
        no_log_file=True,
    )
    print("Models loaded.\n")

    stop_event = threading.Event()

    def recorder_loop():
        """Fetch finalized transcription text and push it to the queue."""
        while not stop_event.is_set():
            text = recorder.text()
            if text and text.strip():
                text_queue.put(("final", text.strip()))

    recorder_thread = threading.Thread(target=recorder_loop, daemon=True)
    recorder_thread.start()

    # Poll text_queue every 50ms and update the GUI
    def poll_text():
        try:
            while True:
                kind, text = text_queue.get_nowait()
                if kind == "partial":
                    window.show_partial(text)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] {text}")
                    window.show_final(text)
        except queue.Empty:
            pass

    timer = QTimer()
    timer.timeout.connect(poll_text)
    timer.start(50)

    try:
        app.exec()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        recorder.stop()
        print("Stopped.")


if __name__ == "__main__":
    main()
