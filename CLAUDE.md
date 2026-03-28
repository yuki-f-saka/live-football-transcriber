# CLAUDE.md — live-football-transcriber

Real-time speech-to-text overlay for macOS. Captures system audio from live football broadcasts via BlackHole 2ch and displays subtitles as a transparent always-on-top window.

---

## Maintenance rule

**When CLAUDE.md is updated, CLAUDE.ja.md must also be updated to stay in sync.**
CLAUDE.ja.md is a Japanese translation of this file for the project owner to read. It is not referenced by Claude Code.

---

## Two implementations

| File | Approach | Key library | Characteristic |
|---|---|---|---|
| `overlay_transcribe.py` | VAD-based chunking | mlx-whisper (Metal GPU) | Low latency, has hallucination filter |
| `overlay_streaming.py` | RealtimeSTT streaming | RealtimeSTT (CPU, tiny.en + small.en) | Displays partial text in real time |

These are intentionally independent — shared logic is not abstracted. When modifying one, be aware of the divergence from the other.

---

## Hardware / platform requirements

- macOS + Apple Silicon (mlx-whisper requires Metal GPU)
- BlackHole 2ch virtual audio driver installed
- macOS Audio MIDI Setup configured with a Multi-Output Device (speakers + BlackHole 2ch)

If these are not set up, the app will crash immediately with a device-not-found error.

---

## How to run

```bash
python overlay_transcribe.py   # VAD mode (recommended)
python overlay_streaming.py    # Streaming mode (shows partial text)
```

On first run, models are downloaded from HuggingFace — this takes a few minutes.

---

## Architecture — thread model (overlay_transcribe.py)

```
audio_callback (real-time, 50ms blocks)
  └─ audio_queue (Queue)
       └─ transcription_worker (background thread)
            └─ text_queue (Queue)
                 └─ poll_text() (Qt timer, 50ms) → SubtitleWindow.show_text()
```

**Never put blocking operations in `audio_callback` — it runs on a real-time thread.**

---

## Key tuning constants

### overlay_transcribe.py

```python
MODEL_SIZE = "mlx-community/whisper-small.en-mlx"  # switch to tiny.en for speed
DEVICE_NAME = "BlackHole 2ch"
SILENCE_RMS_THRESHOLD = 0.03   # intentionally high to filter crowd noise
POST_SPEECH_SILENCE_SECONDS = 0.4  # silence duration that triggers transcription
MIN_SPEECH_SECONDS = 0.3       # utterances shorter than this are ignored
MAX_SPEECH_SECONDS = 1.5       # force-flush for long continuous speech
SUBTITLE_SECONDS = 4.0         # auto-clear timer for displayed subtitle
SCREEN_INDEX = 1               # 0 = main screen, 1 = external monitor
```

### overlay_streaming.py

```python
FINAL_MODEL = "small.en"       # high accuracy for finalized text
REALTIME_MODEL = "tiny.en"     # fast model for partial updates
MAX_PARTIAL_CHARS = 80         # cap to prevent UI overflow on long utterances
SCREEN_INDEX = 1
```

---

## Known issues / gotchas

- **Whisper hallucination**: Crowd noise and BGM cause repeated words or symbol-only output. `overlay_transcribe.py` handles this via `is_hallucination()` and `no_speech_prob > 0.5` filtering. `overlay_streaming.py` has no hallucination filter (delegates to RealtimeSTT's VAD).
- **requirements.txt is outdated**: Actual dependencies are `mlx-whisper` (not `faster-whisper`) and `RealtimeSTT`. System-level deps `ffmpeg` and `portaudio` must be installed via Homebrew.
- **`SILENCE_RMS_THRESHOLD` sensitivity**: Optimal value varies by environment (quiet room vs. TV audio). Too low increases hallucinations.
- **`MAX_SPEECH_SECONDS = 1.5`**: Commentary often runs continuously, so VAD may never detect silence. This constant force-flushes long utterances.

---

## Logging

- Logs written to `transcriber.log` and stdout simultaneously.
- Thread exception handler is in place for post-crash diagnosis.
