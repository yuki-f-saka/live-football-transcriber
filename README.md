# live-football-transcriber

Real-time speech-to-text overlay for live football (soccer) broadcasts on macOS.

Captures system audio and transcribes it using Whisper, displaying subtitles as a transparent overlay at the top of your screen — without interrupting your video player or any other window.

Two scripts are available depending on your preference:

| Script | Description |
|---|---|
| `overlay_transcribe.py` | VAD-based chunking + mlx-whisper (Metal GPU). Low latency, no partial display. |
| `overlay_streaming.py` | RealtimeSTT streaming. Shows partial text in real-time while speaking, confirmed text in green. |

![demo](https://via.placeholder.com/800x120/111111/ffffff?text=Real-time+subtitle+overlay)

## Requirements

- macOS (Apple Silicon recommended)
- Python 3.9+
- [BlackHole 2ch](https://existential.audio/blackhole/) — virtual audio driver to capture system audio
- [ffmpeg](https://ffmpeg.org/)
- [portaudio](https://www.portaudio.com/) — required for `overlay_streaming.py`

```bash
brew install ffmpeg portaudio
```

## Installation

```bash
git clone https://github.com/yuki-f-saka/live-football-transcriber.git
cd live-football-transcriber
pip install -r requirements.txt
```

## Audio Routing Setup (one-time)

To capture system audio while still hearing it through your speakers, create a **Multi-Output Device** in macOS:

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`)
2. Click `+` at the bottom left → **Create Multi-Output Device**
3. Check both **BlackHole 2ch** and your speakers (e.g. MacBook Air Speakers)
4. Enable **Drift Correction** on BlackHole 2ch
5. Right-click the new Multi-Output Device → **Use This Device For Sound Output**

## Usage

Play your football broadcast, then run either script:

### overlay_transcribe.py — VAD + mlx-whisper

```bash
python overlay_transcribe.py
```

- Uses Apple Silicon Metal GPU via [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) for fast inference
- Transcribes after each speech segment ends (VAD-detected silence)
- Subtitle appears in white, disappears after 4 seconds

### overlay_streaming.py — RealtimeSTT streaming

```bash
python overlay_streaming.py
```

- Shows partial (in-progress) text in **white** as you speak
- When the utterance is finalized, text turns **green** and auto-clears after 4 seconds
- Uses two models internally: `tiny.en` for real-time updates, `small.en` for final accuracy
- Feels significantly more real-time than chunk-based approaches

**Quit:** press `Escape`, or `Ctrl+C` in the terminal.

## Configuration

### overlay_transcribe.py

| Variable | Default | Description |
|---|---|---|
| `MODEL_SIZE` | `mlx-community/whisper-small.en-mlx` | mlx-whisper model (`tiny.en` or `small.en` variants) |
| `SILENCE_RMS_THRESHOLD` | `0.03` | RMS level below which audio is treated as silence |
| `POST_SPEECH_SILENCE_SECONDS` | `0.4` | Silence duration after speech to trigger transcription |
| `MAX_SPEECH_SECONDS` | `1.5` | Force-flush after this many seconds of continuous speech |
| `FONT_SIZE` | `30` | Subtitle font size |
| `SUBTITLE_SECONDS` | `4.0` | How long each subtitle stays on screen |
| `SCREEN_INDEX` | `1` | Screen to display overlay on (0 = main, 1 = external) |

### overlay_streaming.py

| Variable | Default | Description |
|---|---|---|
| `FINAL_MODEL` | `small.en` | Model for finalized transcription (accuracy) |
| `REALTIME_MODEL` | `tiny.en` | Model for partial real-time updates (speed) |
| `MAX_PARTIAL_CHARS` | `80` | Max characters shown for partial text (prevents overflow) |
| `FONT_COLOR_PARTIAL` | `white` | Color of in-progress text |
| `FONT_COLOR_FINAL` | `#00e676` | Color of finalized text (bright green) |
| `SUBTITLE_SECONDS` | `4.0` | How long finalized text stays on screen |
| `SCREEN_INDEX` | `1` | Screen to display overlay on (0 = main, 1 = external) |

## How It Works

### overlay_transcribe.py

```
System audio → BlackHole 2ch
                    ↓ 50ms blocks
             RMS-based VAD
             (silence = RMS < 0.03)
                    ↓ speech segment detected
             audio_queue
                    ↓
             mlx-whisper (Metal GPU)
             + hallucination filter
                    ↓
             PyQt6 overlay (white text)
```

### overlay_streaming.py

```
System audio → BlackHole 2ch
                    ↓
             RealtimeSTT
             (Silero VAD + PyAudio)
              ┌─────┴──────┐
         tiny.en        small.en
        (realtime)       (final)
              │              │
        partial text    final text
        (white, live)  (green, 4s)
                    ↓
             PyQt6 overlay
```

## License

MIT — see [LICENSE](LICENSE).

Uses [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (MIT), [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) (MIT), and [OpenAI Whisper](https://github.com/openai/whisper) model weights (MIT).
