#!/usr/bin/env python3
"""
Real-time transcription with macOS overlay subtitle window (PyQt6).

Usage:
    python overlay_transcribe.py

Quit: press Escape, or Ctrl+C in terminal.
"""

import queue
import signal
import sys
import threading
import time
import numpy as np
import sounddevice as sd
import mlx_whisper
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# --- Audio / Model settings ---
MODEL_SIZE      = "mlx-community/whisper-small.en-mlx"
# MODEL_SIZE = "mlx-community/whisper-tiny.en-mlx"
DEVICE_NAME     = "BlackHole 2ch"
SAMPLE_RATE     = 16000

# --- VAD settings ---
SILENCE_RMS_THRESHOLD       = 0.03   # RMS below this is treated as silence (raised to filter crowd noise)
POST_SPEECH_SILENCE_SECONDS = 0.4    # silence duration after speech to trigger transcription
MIN_SPEECH_SECONDS          = 0.3    # speech segments shorter than this are ignored
MAX_SPEECH_SECONDS          = 1.5    # force-flush after this many seconds of continuous speech

# --- Overlay appearance ---
FONT_SIZE            = 30
FONT_COLOR           = "white"
BG_COLOR             = "#111111"
BG_OPACITY           = 200        # 0 (transparent) to 255 (opaque)
SUBTITLE_SECONDS     = 4.0        # seconds before subtitle disappears
SCREEN_MARGIN_Y      = 40         # distance from top of screen (px)
WINDOW_WIDTH_RATIO   = 0.65       # subtitle bar width as fraction of screen width
SCREEN_INDEX         = 1          # screen to show overlay on (0 = main, 1 = external, ...)

# ------------------------------

def find_device_index(name: str) -> int:
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if name in d["name"] and d["max_input_channels"] > 0:
            return i
    available = "\n".join(
        f"  {i}: {d['name']}"
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    )
    raise RuntimeError(f"Device '{name}' not found.\nAvailable:\n{available}")


class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()

        # Window flags
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
            print(f"[warn] SCREEN_INDEX={SCREEN_INDEX} not found ({len(screens)} screen(s) detected). Using screen 0.")
        print(f"Using screen [{SCREEN_INDEX if SCREEN_INDEX < len(screens) else 0}]: {target.name()}")
        screen = target.availableGeometry()  # area excluding the Dock
        win_w = int(screen.width() * WINDOW_WIDTH_RATIO)
        win_h = 90
        x = screen.x() + (screen.width() - win_w) // 2
        y = screen.y() + SCREEN_MARGIN_Y
        self.setGeometry(x, y, win_w, win_h)
        print(f"Overlay window: {win_w}x{win_h} at ({x}, {y})")

        # Subtitle label
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFont(QFont("Helvetica", FONT_SIZE, QFont.Weight.Bold))

        color = QColor(BG_COLOR)
        color.setAlpha(BG_OPACITY)
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {FONT_COLOR};
                background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {BG_OPACITY});
                border-radius: 8px;
                padding: 6px 14px;
            }}
        """)
        self.label.setGeometry(0, 0, win_w, win_h)

        # Timer to auto-clear subtitle
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear)

    def show_text(self, text: str):
        self.label.setText(text)
        self._clear_timer.start(int(SUBTITLE_SECONDS * 1000))

    def _clear(self):
        self.label.setText("")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()


class VadState:
    """Tracks voice activity detection state across audio callbacks."""
    def __init__(self):
        self.is_speaking = False
        self.speech_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self.silence_samples = 0


def main():
    print(f"Loading model '{MODEL_SIZE}'...")
    # Warm up the model (downloads from HuggingFace on first run)
    mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=MODEL_SIZE)
    print("Model loaded.\n")

    device_index = find_device_index(DEVICE_NAME)
    print(f"Input device [{device_index}]: {DEVICE_NAME}")
    print(f"VAD mode  |  silence threshold: {POST_SPEECH_SILENCE_SECONDS}s  |  max chunk: {MAX_SPEECH_SECONDS}s")
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

    # Show startup message to confirm overlay position
    window.show_text("▶ Overlay active — waiting for audio...")

    audio_queue: queue.Queue = queue.Queue()
    text_queue:  queue.Queue = queue.Queue()

    post_speech_silence_samples = int(POST_SPEECH_SILENCE_SECONDS * SAMPLE_RATE)
    min_speech_samples          = int(MIN_SPEECH_SECONDS * SAMPLE_RATE)
    max_speech_samples          = int(MAX_SPEECH_SECONDS * SAMPLE_RATE)

    vad = VadState()

    def audio_callback(indata, _frames, _time_info, status):
        if status:
            print(f"[audio] {status}")

        audio = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(audio ** 2)))
        is_speech = rms > SILENCE_RMS_THRESHOLD

        if is_speech:
            # Active speech: append to buffer and reset silence counter
            vad.is_speaking = True
            vad.silence_samples = 0
            vad.speech_buffer = np.concatenate([vad.speech_buffer, audio])

            # Safety flush for very long continuous speech
            if len(vad.speech_buffer) >= max_speech_samples:
                audio_queue.put(vad.speech_buffer.copy())
                vad.speech_buffer = np.zeros(0, dtype=np.float32)

        elif vad.is_speaking:
            # Silence after speech: keep buffering and count silence samples
            vad.speech_buffer = np.concatenate([vad.speech_buffer, audio])
            vad.silence_samples += len(audio)

            if vad.silence_samples >= post_speech_silence_samples:
                # Enough silence detected — trigger transcription
                if len(vad.speech_buffer) >= min_speech_samples:
                    audio_queue.put(vad.speech_buffer.copy())
                vad.speech_buffer = np.zeros(0, dtype=np.float32)
                vad.silence_samples = 0
                vad.is_speaking = False

    def is_hallucination(text: str) -> bool:
        """Detect Whisper hallucinations: symbol-only output or repeated words."""
        # Reject output with fewer than 4 alphabetic characters (e.g. "...", "!", "St-")
        alpha_chars = sum(c.isalpha() for c in text)
        if alpha_chars < 4:
            return True
        # Reject output where the same word repeats 4+ times consecutively
        words = text.split()
        for i in range(len(words) - 3):
            if len(set(words[i:i + 4])) == 1:
                return True
        return False

    def transcription_worker():
        while True:
            audio_chunk = audio_queue.get()
            if audio_chunk is None:
                break

            result = mlx_whisper.transcribe(
                audio_chunk,
                path_or_hf_repo=MODEL_SIZE,
                language="en",
            )

            # Skip segments where Whisper is not confident there is speech
            segments = result.get("segments", [])
            if segments:
                avg_no_speech = sum(s.get("no_speech_prob", 0) for s in segments) / len(segments)
                if avg_no_speech > 0.5:
                    continue

            text = result["text"].strip()
            if text and not is_hallucination(text):
                text_queue.put(text)

    # Poll text_queue every 50ms and update the GUI
    def poll_text():
        try:
            while True:
                text = text_queue.get_nowait()
                print(f"[{time.strftime('%H:%M:%S')}] {text}")
                window.show_text(text)
        except queue.Empty:
            pass

    timer = QTimer()
    timer.timeout.connect(poll_text)
    timer.start(50)

    worker = threading.Thread(target=transcription_worker, daemon=True)
    worker.start()

    stream = sd.InputStream(
        device=device_index,
        channels=1,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(SAMPLE_RATE * 0.05),  # 50ms blocks for responsive VAD
    )
    stream.start()

    try:
        app.exec()
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        audio_queue.put(None)
        worker.join(timeout=2)
        print("Stopped.")


if __name__ == "__main__":
    main()
