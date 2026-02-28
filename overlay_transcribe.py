#!/usr/bin/env python3
"""
Real-time transcription with macOS overlay subtitle window (PyQt6).

Usage:
    python overlay_transcribe.py

Quit: press Escape, or Ctrl+C in terminal.
"""

import queue
import sys
import threading
import time
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# --- Audio / Model settings ---
MODEL_SIZE      = "small.en"
DEVICE_NAME     = "BlackHole 2ch"
SAMPLE_RATE     = 16000
CHUNK_SECONDS   = 3
OVERLAP_SECONDS = 0.5

# --- Overlay appearance ---
FONT_SIZE            = 20
FONT_COLOR           = "white"
BG_COLOR             = "#111111"
BG_OPACITY           = 200        # 0 (透明) 〜 255 (不透明)
SUBTITLE_SECONDS     = 4.0        # 字幕が消えるまでの秒数
SCREEN_MARGIN_Y      = 40         # 画面上端からの距離 (px)
WINDOW_WIDTH_RATIO   = 0.65       # 画面幅に対するウィンドウ幅の比率

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

        # ウィンドウの設定
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint        # タイトルバーなし
            | Qt.WindowType.WindowStaysOnTopHint     # 常に最前面
            | Qt.WindowType.WindowTransparentForInput  # クリック透過
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 背景透過
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # フォーカスを奪わない

        # 画面サイズに合わせて配置
        screen = QApplication.primaryScreen().availableGeometry()  # Dockを除いた領域
        win_w = int(screen.width() * WINDOW_WIDTH_RATIO)
        win_h = 90
        x = screen.x() + (screen.width() - win_w) // 2
        y = screen.y() + SCREEN_MARGIN_Y  # 上端から配置
        self.setGeometry(x, y, win_w, win_h)
        print(f"Overlay window: {win_w}x{win_h} at ({x}, {y})")

        # 字幕ラベル
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

        # 自動クリア用タイマー
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


def main():
    print(f"Loading model '{MODEL_SIZE}'...")
    model = WhisperModel(MODEL_SIZE, device="auto", compute_type="int8")
    print("Model loaded.\n")

    device_index = find_device_index(DEVICE_NAME)
    print(f"Input device [{device_index}]: {DEVICE_NAME}")
    print(f"Chunk: {CHUNK_SECONDS}s  |  Overlap: {OVERLAP_SECONDS}s")
    print("Listening... (Escape or Ctrl+C to quit)\n")

    app = QApplication(sys.argv)
    window = SubtitleWindow()
    window.show()
    window.raise_()

    # 起動直後にテスト文字を表示して位置確認
    window.show_text("▶ Overlay active — waiting for audio...")

    audio_queue: queue.Queue = queue.Queue()
    text_queue:  queue.Queue = queue.Queue()
    buffer = np.zeros(0, dtype=np.float32)
    chunk_samples   = int(CHUNK_SECONDS    * SAMPLE_RATE)
    overlap_samples = int(OVERLAP_SECONDS  * SAMPLE_RATE)

    def audio_callback(indata, _frames, _time_info, status):
        if status:
            print(f"[audio] {status}")
        audio_queue.put(indata[:, 0].copy())

    def transcription_worker():
        nonlocal buffer
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                break
            buffer = np.concatenate([buffer, chunk])

            if len(buffer) >= chunk_samples:
                audio_chunk = buffer[:chunk_samples].copy()
                buffer = buffer[chunk_samples - overlap_samples:]

                segments, _ = model.transcribe(
                    audio_chunk,
                    language="en",
                    beam_size=1,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                )
                parts = [seg.text.strip() for seg in segments]
                if parts:
                    text_queue.put(" ".join(parts))

    # 100msごとにtext_queueを確認してGUIを更新
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
    timer.start(100)

    worker = threading.Thread(target=transcription_worker, daemon=True)
    worker.start()

    stream = sd.InputStream(
        device=device_index,
        channels=1,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(SAMPLE_RATE * 0.5),
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
