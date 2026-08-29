"""VAD-based chunking + mlx-whisper (Metal GPU) transcription backend.

Thread model::

    audio_callback (real-time, 50 ms blocks)
      └─ audio_queue (Queue)
           └─ transcription_worker (background thread)
                └─ OverlayApp.text_queue → SubtitleWindow (Qt timer, 50 ms)

Never put blocking operations in ``audio_callback`` — it runs on a real-time thread.
"""

from __future__ import annotations

import logging
import queue
import threading

import numpy as np
import sounddevice as sd

from .app import OverlayApp
from .audio import find_device_index
from .config import Settings
from .text_filters import is_hallucination, looks_like_prompt_echo
from .vocabulary import Vocabulary

log = logging.getLogger(__name__)


class VadState:
    """Tracks voice activity detection state across audio callbacks."""

    def __init__(self):
        self.is_speaking = False
        self.speech_buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self.silence_samples = 0


def run(settings: Settings) -> int:
    import mlx_whisper  # heavy import; keep it local so `--help` stays fast

    model = settings.resolved_model()
    log.info("Loading model '%s'...", model)
    # Warm up the model (downloads from HuggingFace on first run)
    mlx_whisper.transcribe(np.zeros(settings.sample_rate, dtype=np.float32), path_or_hf_repo=model)
    log.info("Model loaded.")

    device_index = find_device_index(settings.device)
    log.info("Input device [%d]: %s", device_index, settings.device)
    log.info(
        "VAD mode  |  silence threshold: %ss  |  max chunk: %ss",
        settings.post_speech_silence, settings.max_speech,
    )
    log.info("Listening... (Escape or Ctrl+C to quit)")

    vocab = Vocabulary(settings.language, settings.player_names(), enabled=settings.vocabulary)
    prompt = vocab.prompt
    if prompt:
        log.info("Vocabulary prompt: %s", prompt)

    app = OverlayApp(settings)
    gain = app.attach_gain_control(settings.gain)
    # Show startup message to confirm overlay position
    app.window.show_text("▶ Overlay active — waiting for audio...")

    audio_queue: "queue.Queue[np.ndarray | None]" = queue.Queue()

    sr = settings.sample_rate
    post_speech_silence_samples = int(settings.post_speech_silence * sr)
    min_speech_samples = int(settings.min_speech * sr)
    max_speech_samples = int(settings.max_speech * sr)
    silence_threshold = settings.silence_threshold

    vad = VadState()

    def audio_callback(indata, _frames, _time_info, status):
        if status:
            log.warning("Audio stream status: %s", status)
        try:
            audio = gain.apply(indata[:, 0].copy())
            rms = float(np.sqrt(np.mean(audio ** 2)))
            is_speech = rms > silence_threshold

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
        except Exception:
            log.exception("Exception in audio_callback")

    def transcription_worker():
        while True:
            audio_chunk = audio_queue.get()
            if audio_chunk is None:
                break
            try:
                result = mlx_whisper.transcribe(
                    audio_chunk,
                    path_or_hf_repo=model,
                    language=settings.language,
                    initial_prompt=prompt,
                )

                # Skip segments where Whisper is not confident there is speech
                segments = result.get("segments", [])
                if segments:
                    avg_no_speech = sum(s.get("no_speech_prob", 0) for s in segments) / len(segments)
                    if avg_no_speech > 0.5:
                        continue

                text = result["text"].strip()
                if not text or is_hallucination(text) or looks_like_prompt_echo(text, prompt):
                    continue
                text = vocab.correct(text)
                log.info(text)
                app.push_final(text)
            except Exception:
                log.exception("Exception in transcription_worker")

    worker = threading.Thread(target=transcription_worker, name="transcription_worker", daemon=True)
    worker.start()

    stream = sd.InputStream(
        device=device_index,
        channels=1,
        samplerate=sr,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(sr * 0.05),  # 50 ms blocks for responsive VAD
    )
    stream.start()

    def shutdown():
        stream.stop()
        stream.close()
        audio_queue.put(None)
        worker.join(timeout=2)
        log.info("Stopped.")

    return app.exec(on_exit=shutdown)
