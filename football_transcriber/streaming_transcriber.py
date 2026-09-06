"""RealtimeSTT streaming backend.

Displays partial (in-progress) text while speaking, then overwrites it with
the finalized transcript from the larger model when the utterance ends.

Partial text: updated live (tiny.en for speed)
Final text:   auto-clears after ``subtitle_seconds`` (small.en for accuracy)
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
import sounddevice as sd

from .app import OverlayApp
from .audio import find_device_index
from .config import Settings
from .text_filters import looks_like_prompt_echo
from .vocabulary import Vocabulary

log = logging.getLogger(__name__)


def run(settings: Settings) -> int:
    from RealtimeSTT import AudioToTextRecorder  # heavy import; keep local

    device_index = find_device_index(settings.device)
    final_model = settings.resolved_model()
    realtime_model = settings.resolved_realtime_model()
    log.info("Input device [%d]: %s", device_index, settings.device)
    log.info("Final model: %s  |  Realtime model: %s", final_model, realtime_model)
    log.info("Listening... (Escape or Ctrl+C to quit)")

    vocab = Vocabulary(settings.language, settings.player_names(), enabled=settings.vocabulary)
    prompt = vocab.prompt
    if prompt:
        log.info("Vocabulary prompt: %s", prompt)

    app = OverlayApp(settings)
    gain = app.attach_gain_control(settings.gain)
    app.window.show_partial("▶ Overlay active — loading models...")

    max_partial = settings.max_partial_chars

    def on_partial(text: str):
        text = text.strip()
        if text:
            # Show only the trailing N characters to prevent overflow during long speech
            app.push_partial(vocab.correct(text)[-max_partial:])

    log.info("Loading models (this may take a moment on first run)...")
    recorder = AudioToTextRecorder(
        model=final_model,
        realtime_model_type=realtime_model,
        language=settings.language,
        use_microphone=False,                  # we capture with sounddevice and feed_audio() so gain can be applied
        device="cpu",                          # no CUDA on Mac; use cpu
        compute_type="int8",
        enable_realtime_transcription=True,
        use_main_model_for_realtime=False,     # tiny.en for partial, small.en for final
        realtime_processing_pause=0.1,
        init_realtime_after_seconds=0.2,
        on_realtime_transcription_update=on_partial,
        silero_sensitivity=0.4,
        post_speech_silence_duration=settings.post_speech_silence,
        min_length_of_recording=settings.min_speech,
        beam_size=1,
        beam_size_realtime=1,
        spinner=False,
        no_log_file=True,
        initial_prompt=prompt,
        initial_prompt_realtime=prompt,
    )
    log.info("Models loaded.")

    sr = settings.sample_rate

    def audio_callback(indata, _frames, _time_info, status):
        # Real-time thread: apply gain, convert to int16 PCM and hand off. No blocking here.
        if status:
            log.warning("Audio stream status: %s", status)
        try:
            audio = gain.apply(indata[:, 0])
            recorder.feed_audio((audio * 32767).astype(np.int16).tobytes(), original_sample_rate=sr)
        except Exception:
            log.exception("Exception in audio_callback")

    stream = sd.InputStream(
        device=device_index,
        channels=1,
        samplerate=sr,
        dtype="float32",
        callback=audio_callback,
        blocksize=int(sr * 0.05),  # 50 ms blocks
    )
    stream.start()

    stop_event = threading.Event()

    def recorder_loop():
        """Fetch finalized transcription text and push it to the queue."""
        while not stop_event.is_set():
            text = recorder.text()
            if text and text.strip():
                text = text.strip()
                if looks_like_prompt_echo(text, prompt):
                    continue
                text = vocab.correct(text)
                log.info("[%s] %s", time.strftime("%H:%M:%S"), text)
                app.push_final(text)

    recorder_thread = threading.Thread(target=recorder_loop, name="recorder_loop", daemon=True)
    recorder_thread.start()

    def shutdown():
        stop_event.set()
        stream.stop()
        stream.close()
        try:
            recorder.shutdown()
        except Exception:
            log.exception("Error while shutting down recorder")
        log.info("Stopped.")

    return app.exec(on_exit=shutdown)
