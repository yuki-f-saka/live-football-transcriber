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
├── app.py                    # OverlayApp: QApplication, SIGINT handling, text_queue → window, gain/keyboard wiring
├── overlay.py                # SubtitleWindow (PyQt6) + status badge
├── transcriber.py            # VAD chunking + mlx-whisper backend  ("vad" mode)
├── streaming_transcriber.py  # RealtimeSTT backend                 ("streaming" mode)
├── audio.py                  # device lookup, Gain, KeyboardController (terminal keys)
├── vocabulary.py             # Whisper initial_prompt + term/player-name corrections
├── text_filters.py           # is_hallucination(), looks_like_prompt_echo()
├── highlights.py             # keyword → event detection with actions (log/notify/sound)
└── macos.py                  # PyObjC: overlay over fullscreen apps / all Spaces
tests/                        # pytest (pure-Python units; no audio/GPU needed)
overlay_transcribe.py         # thin wrapper == football-transcriber vad
overlay_streaming.py          # thin wrapper == football-transcriber streaming
```

The two backends (`transcriber.py`, `streaming_transcriber.py`) are still intentionally separate implementations — only the overlay, config, vocabulary, highlights and gain plumbing are shared. When modifying one backend, check whether the other needs the same change.

---

## Hardware / platform requirements

- macOS + Apple Silicon (mlx-whisper requires Metal GPU)
- BlackHole 2ch virtual audio driver installed
- macOS Audio MIDI Setup configured with a Multi-Output Device (speakers + BlackHole 2ch)
- `pyobjc-framework-Cocoa` for the fullscreen overlay (optional; logs a warning if missing)

If the audio device is not set up, the app exits immediately with a device-not-found error listing available inputs (`--list-devices`).

---

## How to run

```bash
pip install -e .                       # provides the `football-transcriber` command
football-transcriber vad               # VAD mode (recommended)   == python overlay_transcribe.py
football-transcriber streaming         # shows partial text       == python overlay_streaming.py
football-transcriber --help
football-transcriber vad --lang ja --screen 0 --players "三笘,久保"
football-transcriber vad --highlights goal,penalty --notify
football-transcriber --screen 0 --gain 1.5 --save    # persist settings to the config file
python -m pytest
```

On first run, models are downloaded from HuggingFace — this takes a few minutes.

Runtime keys (typed in the terminal; the overlay itself is click-through and never has focus):
`+`/`-`/Up/Down = input gain, `0` = reset, `m` = mute, `q`/Esc = quit. Gain changes are persisted immediately.

---

## Settings precedence

`Settings` defaults (`config.py`) < config file `~/.config/football-transcriber/config.json` (or `--config PATH`) < CLI flags.
`Settings.save_key()` updates a single key in the file without clobbering the rest (used for gain). `--show-config` prints the effective settings.

Model resolution (`Settings.resolved_model()`): short sizes (`tiny/base/small/medium/large`) map to `mlx-community/whisper-<size>.en-mlx` for English and multilingual `whisper-<size>-mlx` otherwise; streaming mode maps to faster-whisper names (`small.en` / `small`). Japanese defaults to `medium`.

---

## Architecture — thread model (vad mode)

```
audio_callback (real-time, 50ms blocks) → Gain.apply() → RMS VAD
  └─ audio_queue (Queue)
       └─ transcription_worker (background thread)
            ├─ mlx_whisper.transcribe(initial_prompt=vocab.prompt)
            ├─ no_speech_prob / is_hallucination / looks_like_prompt_echo filters
            ├─ vocab.correct()  →  OverlayApp.push_final()
            └─ highlights.handle()
                 └─ text_queue → poll (Qt timer, 50ms) → SubtitleWindow.show_text()
KeyboardController (thread, stdin cbreak) → Gain.set() → push_status() + Settings.save_key("gain")
```

Streaming mode captures with sounddevice too (`use_microphone=False`) and hands int16 PCM to `AudioToTextRecorder.feed_audio()` so the same Gain applies.

**Never put blocking operations in `audio_callback` — it runs on a real-time thread.** (File I/O for gain persistence happens on the keyboard thread, not the audio thread.)

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
gain = 1.0                   # input gain, 0..5                                  (--gain, +/- keys)
highlight_cooldown = 10.0    # seconds before the same event fires again
```

---

## Known issues / gotchas

- **Whisper hallucination**: Crowd noise and BGM cause repeated words or symbol-only output. VAD mode filters via `no_speech_prob > 0.5`, `is_hallucination()` and `looks_like_prompt_echo()` (Whisper sometimes parrots the `initial_prompt` on silence). Streaming mode only applies the prompt-echo check (VAD is delegated to RealtimeSTT/Silero).
- **`initial_prompt` on short chunks**: 1.5 s chunks with a long prompt can increase prompt echoes; keep `FOOTBALL_TERMS_*` short. `--no-vocab` disables it.
- **Player-name fuzzy correction only handles Latin script** (`_WORD_RE` in `vocabulary.py`); Japanese names are only boosted via the prompt.
- **`silence_threshold` sensitivity**: Optimal value varies by environment. Too low increases hallucinations. Runtime gain (`+`/`-`) effectively shifts it.
- **`max_speech = 1.5`**: Commentary runs continuously, so VAD may never detect silence; this force-flushes long utterances.
- **Fullscreen overlay** relies on `NSWindowCollectionBehaviorFullScreenAuxiliary` + `NSScreenSaverWindowLevel` applied after `show()`. If Qt ever recreates the native window (e.g. screen change), the flags would need re-applying.
- **Keyboard control needs a TTY**: when stdin is not a terminal (launched from an IDE/launchd) gain can only be set with `--gain`.

---

## Logging

- Logs written to `transcriber.log` (`--log-file`) and stdout simultaneously. Root level INFO, `football_transcriber.*` at DEBUG.
- Highlight markers go to `highlights.log` (`--highlight-log`).
- Thread exception handler is in place for post-crash diagnosis.
