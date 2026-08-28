# CLAUDE.md — live-football-transcriber

Real-time speech-to-text overlay for macOS. Captures system audio from live football broadcasts via BlackHole 2ch and displays subtitles as a transparent always-on-top window.

---

## Maintenance rule

**When CLAUDE.md is updated, CLAUDE.ja.md must also be updated to stay in sync.**
CLAUDE.ja.md is a Japanese translation of this file for the project owner to read. It is not referenced by Claude Code.

---

## Package layout

```
football_transcriber/
├── cli.py                    # entry point: football-transcriber [vad|streaming] [options]
├── config.py                 # Settings dataclass (all constants) + JSON config file + model resolution
├── app.py                    # OverlayApp: QApplication, SIGINT handling, text_queue → window
├── overlay.py                # SubtitleWindow (PyQt6)
├── transcriber.py            # VAD chunking + mlx-whisper backend  ("vad" mode)
├── streaming_transcriber.py  # RealtimeSTT backend                 ("streaming" mode)
├── audio.py                  # input device lookup
└── text_filters.py           # is_hallucination()
tests/                        # pytest (pure-Python units; no audio/GPU needed)
overlay_transcribe.py         # thin wrapper == football-transcriber vad
overlay_streaming.py          # thin wrapper == football-transcriber streaming
```

The two backends (`transcriber.py`, `streaming_transcriber.py`) are still intentionally separate implementations — only the overlay, config and app bootstrap are shared. When modifying one backend, check whether the other needs the same change.

---

## Hardware / platform requirements

- macOS + Apple Silicon (mlx-whisper requires Metal GPU)
- BlackHole 2ch virtual audio driver installed
- macOS Audio MIDI Setup configured with a Multi-Output Device (speakers + BlackHole 2ch)

If the audio device is not set up, the app exits immediately with a device-not-found error listing available inputs (`--list-devices`).

---

## How to run

```bash
pip install -e .                       # provides the `football-transcriber` command
football-transcriber vad               # VAD mode (recommended)   == python overlay_transcribe.py
football-transcriber streaming         # shows partial text       == python overlay_streaming.py
football-transcriber --help
football-transcriber --screen 0 --save # persist settings to the config file
python -m pytest
```

On first run, models are downloaded from HuggingFace — this takes a few minutes.

---

## Settings precedence

`Settings` defaults (`config.py`) < config file `~/.config/football-transcriber/config.json` (or `--config PATH`) < CLI flags.
`Settings.save_key()` updates a single key in the file without clobbering the rest. `--show-config` prints the effective settings.

Model resolution (`Settings.resolved_model()`): short sizes (`tiny/base/small/medium`) map to `mlx-community/whisper-<size>.en-mlx`; streaming mode uses faster-whisper names (`small.en`).

---

## Architecture — thread model (vad mode)

```
audio_callback (real-time, 50ms blocks) → RMS VAD
  └─ audio_queue (Queue)
       └─ transcription_worker (background thread)
            ├─ mlx_whisper.transcribe()
            ├─ no_speech_prob / is_hallucination filters
            └─ OverlayApp.push_final()
                 └─ text_queue → poll (Qt timer, 50ms) → SubtitleWindow.show_text()
```

**Never put blocking operations in `audio_callback` — it runs on a real-time thread.**

---

## Key tuning constants (`config.py` → `Settings`)

```python
device = "BlackHole 2ch"
silence_threshold = 0.03     # RMS; intentionally high to filter crowd noise    (--threshold)
post_speech_silence = 0.4    # silence that triggers transcription              (--silence)
min_speech = 0.3             # shorter utterances are ignored                    (--min-speech)
max_speech = 1.5             # force-flush for continuous commentary             (--max-speech)
max_partial_chars = 80       # streaming: cap partial text to avoid overflow
subtitle_seconds = 4.0       # auto-clear timer                                  (--subtitle-seconds)
screen = 1                   # 0 = main, 1 = external                            (--screen)
```

---

## Known issues / gotchas

- **Whisper hallucination**: Crowd noise and BGM cause repeated words or symbol-only output. VAD mode filters via `no_speech_prob > 0.5` and `is_hallucination()`. Streaming mode has no hallucination filter (VAD is delegated to RealtimeSTT/Silero).
- **`silence_threshold` sensitivity**: Optimal value varies by environment. Too low increases hallucinations.
- **`max_speech = 1.5`**: Commentary runs continuously, so VAD may never detect silence; this force-flushes long utterances.

---

## Logging

- Logs written to `transcriber.log` (`--log-file`) and stdout simultaneously. Root level INFO, `football_transcriber.*` at DEBUG.
- Thread exception handler is in place for post-crash diagnosis.
