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
from faster_whisper import WhisperModel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

# --- Audio / Model settings ---
MODEL_SIZE      = "small.en"
DEVICE_NAME     = "BlackHole 2ch"
SAMPLE_RATE     = 16000

# --- VAD settings ---
SILENCE_RMS_THRESHOLD       = 0.01   # この値以下のRMSは無音とみなす
POST_SPEECH_SILENCE_SECONDS = 0.4    # 発話終了後この秒数の無音で文字起こしをトリガー
MIN_SPEECH_SECONDS          = 0.3    # これ未満の発話は無視する
MAX_SPEECH_SECONDS          = 1.5    # 連続発話がこの秒数を超えたら強制的にフラッシュ

# --- Overlay appearance ---
FONT_SIZE            = 30
FONT_COLOR           = "white"
BG_COLOR             = "#111111"
BG_OPACITY           = 200        # 0 (透明) 〜 255 (不透明)
SUBTITLE_SECONDS     = 4.0        # 字幕が消えるまでの秒数
SCREEN_MARGIN_Y      = 40         # 画面上端からの距離 (px)
WINDOW_WIDTH_RATIO   = 0.65       # 画面幅に対するウィンドウ幅の比率
SCREEN_INDEX         = 1          # 字幕を表示するスクリーン番号 (0=メイン, 1=外部ディスプレイ, ...)

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
        screens = QApplication.screens()
        target = screens[SCREEN_INDEX] if SCREEN_INDEX < len(screens) else screens[0]
        if SCREEN_INDEX >= len(screens):
            print(f"[warn] SCREEN_INDEX={SCREEN_INDEX} が存在しません (検出: {len(screens)}画面)。0番を使用します。")
        print(f"Using screen [{SCREEN_INDEX if SCREEN_INDEX < len(screens) else 0}]: {target.name()}")
        screen = target.availableGeometry()  # Dockを除いた領域
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


class VadState:
    """音声区間検出のための状態管理"""
    def __init__(self):
        self.is_speaking = False
        self.speech_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self.silence_samples = 0


def main():
    print(f"Loading model '{MODEL_SIZE}'...")
    model = WhisperModel(MODEL_SIZE, device="auto", compute_type="int8")
    print("Model loaded.\n")

    device_index = find_device_index(DEVICE_NAME)
    print(f"Input device [{device_index}]: {DEVICE_NAME}")
    print(f"VAD mode  |  silence threshold: {POST_SPEECH_SILENCE_SECONDS}s  |  max chunk: {MAX_SPEECH_SECONDS}s")
    print("Listening... (Escape or Ctrl+C to quit)\n")

    app = QApplication(sys.argv)

    # Ctrl+C (SIGINT) を受け取ったら正常終了する
    signal.signal(signal.SIGINT, lambda *_: QApplication.quit())
    # app.exec() はC++ループなのでタイマーでPythonにシグナル処理の機会を与える
    sigint_timer = QTimer()
    sigint_timer.start(200)
    sigint_timer.timeout.connect(lambda: None)

    window = SubtitleWindow()
    window.show()
    window.raise_()

    # 起動直後にテスト文字を表示して位置確認
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
            # 発話中: バッファに追加、無音カウンタリセット
            vad.is_speaking = True
            vad.silence_samples = 0
            vad.speech_buffer = np.concatenate([vad.speech_buffer, audio])

            # 長時間連続発話のセーフティフラッシュ
            if len(vad.speech_buffer) >= max_speech_samples:
                audio_queue.put(vad.speech_buffer.copy())
                vad.speech_buffer = np.zeros(0, dtype=np.float32)

        elif vad.is_speaking:
            # 発話後の無音: バッファに追加しつつ無音サンプル数を計上
            vad.speech_buffer = np.concatenate([vad.speech_buffer, audio])
            vad.silence_samples += len(audio)

            if vad.silence_samples >= post_speech_silence_samples:
                # 十分な無音 → 文字起こしトリガー
                if len(vad.speech_buffer) >= min_speech_samples:
                    audio_queue.put(vad.speech_buffer.copy())
                vad.speech_buffer = np.zeros(0, dtype=np.float32)
                vad.silence_samples = 0
                vad.is_speaking = False

    def transcription_worker():
        while True:
            audio_chunk = audio_queue.get()
            if audio_chunk is None:
                break

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
        blocksize=int(SAMPLE_RATE * 0.05),  # 50ms ブロック: VAD応答性のため短く
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
