# live-football-transcriber

Real-time speech-to-text overlay for live football (soccer) broadcasts on macOS.

Captures system audio and transcribes it using Whisper, displaying subtitles as a transparent overlay at the top of your screen — without interrupting your video player or any other window.

Two transcription modes are available:

| Mode | Description |
|---|---|
| `vad` (`overlay_transcribe.py`) | VAD-based chunking + mlx-whisper (Metal GPU). Low latency, hallucination filter. **Recommended.** |
| `streaming` (`overlay_streaming.py`) | RealtimeSTT streaming. Shows partial text in real-time while speaking. |

## Features

- Transparent, click-through subtitle bar — shown on **all Spaces and over fullscreen apps**
- **Football vocabulary**: Whisper prompt hints + auto-correction of terms and player names (`--players "Haaland,Salah"`), with explicit aliases for stubborn mis-hearings (`--players "Saka=Sacker|Sarker"`)
- **Runtime volume control** with `+`/`-` keys, persisted between sessions
- **Japanese** (and other languages) via `--lang ja`
- **Highlight detection**: goal / penalty / red card / VAR … → timestamped log, macOS notification, sound
- All settings via CLI flags or `~/.config/football-transcriber/config.json`

## Requirements

- macOS (Apple Silicon required for `vad` mode — mlx-whisper uses the Metal GPU)
- Python 3.10+
- [BlackHole 2ch](https://existential.audio/blackhole/) — virtual audio driver to capture system audio
- [ffmpeg](https://ffmpeg.org/)
- [portaudio](https://www.portaudio.com/) — required for `streaming` mode

```bash
brew install ffmpeg portaudio
```

## Installation

```bash
git clone https://github.com/yuki-f-saka/live-football-transcriber.git
cd live-football-transcriber
pip install -e .              # core (vad mode) — installs the `football-transcriber` command
pip install -e ".[streaming]" # also RealtimeSTT for streaming mode
```

## Audio Routing Setup (one-time)

To capture system audio while still hearing it through your speakers, create a **Multi-Output Device** in macOS:

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`)
2. Click `+` at the bottom left → **Create Multi-Output Device**
3. Check both **BlackHole 2ch** and your speakers (e.g. MacBook Air Speakers)
4. Enable **Drift Correction** on BlackHole 2ch
5. Right-click the new Multi-Output Device → **Use This Device For Sound Output**

## Usage

Play your football broadcast, then:

```bash
football-transcriber                 # vad mode (default)
football-transcriber streaming       # streaming mode with partial text
football-transcriber --help          # all options
football-transcriber --list-devices  # find your input device

# The old entry points still work and accept the same flags:
python overlay_transcribe.py --screen 0
python overlay_streaming.py
```

Examples:

```bash
# Boost recognition of the players on the pitch (also fixes "Harland" → "Haaland")
football-transcriber --players "Haaland,Salah,De Bruyne"
football-transcriber --players-file squad.txt        # one name (or alias spec) per line

# Fuzzy matching gives up below 0.8 similarity, so "Sacker" never becomes "Saka".
# Aliases are matched exactly, which fixes those cases:
football-transcriber --players "Saka=Sacker|Sarker,Rice=Rise,Odegaard=Ode Guard"
```

The canonical name (left of `=`) is what appears in the subtitle, so spell it the way
you want to read it. Aliases are never fed to Whisper as prompt hints — they are wrong
spellings by definition — and they never invent or duplicate a first name
(`Sacker` → `Saka`, `Kai Havits` → `Kai Havertz`).

Note that Whisper's `initial_prompt` holds only ~224 tokens; a full 25-man squad plus the
built-in football terms already uses ~150-180, so two squads at once will be truncated.

```bash
# Japanese commentary (multilingual model, defaults to medium)
football-transcriber --lang ja --model small

# Detect highlights → highlights.log + macOS notification
football-transcriber --highlights goal,penalty,red_card --notify

# Overlay on the main screen, larger font, start at 1.5x input gain
football-transcriber --screen 0 --font-size 36 --gain 1.5

# Save the current flags as defaults (~/.config/football-transcriber/config.json)
football-transcriber --screen 0 --players "Haaland,Salah" --save
```

**While running** (keys typed in the terminal — the overlay is click-through):

| Key | Action |
|---|---|
| `+` / `=` / ↑ | Input gain up (0.1 steps) |
| `-` / `_` / ↓ | Input gain down |
| `0` | Reset gain to 1.0 |
| `m` | Mute / unmute |
| `q` / Esc / Ctrl+C | Quit |

The current gain is shown briefly in the corner of the subtitle bar and saved immediately, so it is restored next time.

## Configuration

Settings resolve as: built-in defaults → config file → CLI flags. Use `--show-config` to print the effective values and `--save` to persist them.

| Setting | Flag | Default | Description |
|---|---|---|---|
| `device` | `--device` | `BlackHole 2ch` | Input device name (substring) |
| `model` | `--model` | `small` (`ja`: `medium`) | `tiny`/`base`/`small`/`medium`/`large` or a full model name |
| `language` | `--lang` | `en` | Whisper language; non-English switches to multilingual models |
| `gain` | `--gain` | `1.0` | Input gain multiplier (0 = mute … 5) |
| `silence_threshold` | `--threshold` | `0.03` | RMS below which audio is treated as silence (vad) |
| `post_speech_silence` | `--silence` | `0.4` | Silence after speech that triggers transcription (s) |
| `min_speech` | `--min-speech` | `0.3` | Ignore utterances shorter than this (s) |
| `max_speech` | `--max-speech` | `1.5` | Force-flush after this many seconds of continuous speech (vad) |
| `vocabulary` | `--no-vocab` | on | Football prompt hints + corrections |
| `players` | `--players`, `--players-file` | — | Player/team names to boost and auto-correct; `Name=alias\|alias` for exact fixes |
| `highlights` | `--highlights` | off | Events to detect: `goal,penalty,red_card,yellow_card,var,offside,free_kick,corner,substitution` or `all` |
| `highlight_notify` | `--notify` | off | macOS notification per event |
| `highlight_sound` | `--highlight-sound` | — | Sound file to play per event |
| `highlight_log` | `--highlight-log` | `highlights.log` | Timestamped marker file (for clipping) |
| `font_size` | `--font-size` | `30` | Subtitle font size |
| `subtitle_seconds` | `--subtitle-seconds` | `4.0` | How long each subtitle stays on screen |
| `screen` | `--screen` | `1` | Screen to display on (0 = main, 1 = external) |
| `fullscreen_overlay` | `--no-fullscreen` | on | Show over fullscreen apps / all Spaces (PyObjC) |
| `max_partial_chars` | — | `80` | Max characters of partial text (streaming) |

## How It Works

### vad mode

```
System audio → BlackHole 2ch
                    ↓ 50ms blocks × gain
             RMS-based VAD
             (silence = RMS < 0.03)
                    ↓ speech segment detected
             audio_queue
                    ↓
             mlx-whisper (Metal GPU)
             + football prompt
             + hallucination filter
             + term / name correction
                    ↓
        PyQt6 overlay  +  highlight detection
```

### streaming mode

```
System audio → BlackHole 2ch
                    ↓ sounddevice × gain → feed_audio()
             RealtimeSTT
             (Silero VAD)
              ┌─────┴──────┐
         tiny.en        small.en
        (realtime)       (final)
              │              │
        partial text    final text (+ corrections, highlights)
                    ↓
             PyQt6 overlay
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

## License

MIT — see [LICENSE](LICENSE).

Uses [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (MIT), [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) (MIT), and [OpenAI Whisper](https://github.com/openai/whisper) model weights (MIT).
