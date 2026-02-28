# live-football-transcriber

Real-time speech-to-text overlay for live football (soccer) broadcasts on macOS.

Captures system audio and transcribes it using [faster-whisper](https://github.com/SYSTRAN/faster-whisper), displaying subtitles as a transparent overlay at the top of your screen — without interrupting your video player or any other window.

![demo](https://via.placeholder.com/800x120/111111/ffffff?text=Real-time+subtitle+overlay)

## Requirements

- macOS
- Python 3.9+
- [BlackHole 2ch](https://existential.audio/blackhole/) — virtual audio driver to capture system audio
- [ffmpeg](https://ffmpeg.org/)

```bash
brew install ffmpeg
```

## Installation

```bash
git clone https://github.com/funesaka/live-football-transcriber.git
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

Play your football broadcast, then run:

```bash
python overlay_transcribe.py
```

A semi-transparent subtitle bar will appear at the top of your screen. Transcription starts automatically.

**Quit:** press `Escape`, or `Ctrl+C` in the terminal.

## Configuration

Edit the constants at the top of `overlay_transcribe.py`:

| Variable | Default | Description |
|---|---|---|
| `MODEL_SIZE` | `small.en` | Whisper model (`tiny.en`, `base.en`, `small.en`, `medium.en`) |
| `CHUNK_SECONDS` | `3` | Audio chunk length — lower = faster, less accurate |
| `FONT_SIZE` | `20` | Subtitle font size |
| `SUBTITLE_SECONDS` | `4.0` | How long each subtitle stays on screen |
| `SCREEN_MARGIN_Y` | `40` | Distance from top of screen (px) |
| `WINDOW_WIDTH_RATIO` | `0.65` | Subtitle bar width as fraction of screen width |

### Model size tradeoffs

| Model | Speed | Accuracy | VRAM |
|---|---|---|---|
| `tiny.en` | Fastest | Lower | ~1 GB |
| `base.en` | Fast | Good | ~1 GB |
| `small.en` | Balanced ← default | High | ~2 GB |
| `medium.en` | Slower | Higher | ~5 GB |

## How It Works

```
System audio → BlackHole 2ch (virtual device)
                     ↓
              sounddevice captures audio
                     ↓
         faster-whisper transcribes in chunks
                     ↓
         PyQt6 overlay displays subtitles
```

Three threads run in parallel:
- **Main thread**: PyQt6 GUI event loop
- **Transcription thread**: runs faster-whisper on audio chunks
- **Audio callback**: feeds raw audio into a queue

## License

MIT — see [LICENSE](LICENSE).

Uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) and [OpenAI Whisper](https://github.com/openai/whisper) model weights (MIT).
