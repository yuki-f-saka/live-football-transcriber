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
├── audio.py                  # device lookup, Gain, KeyboardController, InputMonitor
├── vocabulary.py             # Whisper initial_prompt + term/player-name corrections + aliases
├── chunking.py               # where to cut a force-flushed speech buffer (quiet block + carry-over)
├── text_filters.py           # is_hallucination(), looks_like_prompt_echo()
├── highlights.py             # keyword → event detection with actions (log/notify/sound)
└── macos.py                  # PyObjC: accessory policy + overlay over fullscreen apps / all Spaces
tests/                        # pytest (pure-Python units; no audio/GPU needed)
docs/ARCHITECTURE.md          # the full processing flow + the invariants a change must not break
docs/QUALITY.md               # ruff / mypy / pytest: what is configured, why, and what is not covered
docs/DEVELOPMENT-POLICY.md    # how much of a change has to be read, and what the gates cannot cover
overlay_transcribe.py         # thin wrapper == football-transcriber vad
overlay_streaming.py          # thin wrapper == football-transcriber streaming
```

The two backends (`transcriber.py`, `streaming_transcriber.py`) are still intentionally separate implementations — only the overlay, config, app bootstrap, vocabulary, highlights and gain plumbing are shared. When modifying one backend, check whether the other needs the same change.

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
football-transcriber vad --players "Haaland,Salah,De Bruyne"   # boost + auto-correct names
football-transcriber vad --players "Saka=Sacker|Sarker"        # exact alias for a stubborn mis-hearing
football-transcriber vad --players-file squads/arsenal.txt     # one name (or alias spec) per line
football-transcriber vad --lang ja --screen 0 --players "三笘,久保"
football-transcriber vad --highlights goal,penalty --notify
football-transcriber --screen 0 --gain 1.5 --save    # persist settings to the config file
```

On first run, models are downloaded from HuggingFace — this takes a few minutes.

Runtime keys (typed in the terminal; the overlay itself is click-through and never has focus):
`+`/`-`/Up/Down = input gain, `0` = reset, `m` = mute, `q`/Esc = quit. Gain changes are persisted immediately.

---

## Quality gates

`ruff check .`, `mypy` and `pytest` must all pass before committing — that is what
"green" means here. Configured in `pyproject.toml`, run by `.github/workflows/ci.yml`
on every push and pull request.

CI runs on Linux, so anything touching CoreAudio, Metal or the window server is
**not** covered there and has to be verified by running the app on the Mac.

Rule selection, the mypy configuration constraints and what to tighten next:
[`docs/QUALITY.md`](docs/QUALITY.md).

A green suite is not the same answer for every file. Roughly 300 lines — the
`audio_callback` bodies, `macos.py`, the `OverlayApp` wiring — cannot be executed by
any gate and have to be read on change; the pure modules are fully reachable from
`pytest`, and **a finding in one of them ships with a test that states the requirement**.
The reasoning, and what would shrink that 300: [`docs/DEVELOPMENT-POLICY.md`](docs/DEVELOPMENT-POLICY.md).

---

## Player names and aliases (`vocabulary.py`)

`--players` / `--players-file` entries accept a spec form:

```
Bukayo Saka                      # name only: prompt boost + fuzzy correction
Saka=Sacker|Sarker               # canonical=alias|alias — matched exactly
Martin Odegaard=Ode Guard        # aliases may span several words
```

The canonical name is what gets written into the subtitle, so spell it the way you
want to read it: `Saka=Sacker` yields "Saka", `Bukayo Saka=Sacker` yields the full name.
Matching runs longest-phrase-first, exact before fuzzy, and only on windows starting
with a capitalised word (so "salad" never becomes "Salah"). Raw specs are stored in
`Settings.players`, so `--save` and `--show-config` round-trip them unparsed.

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
InputMonitor (thread, every 20s) → WARNING naming why no subtitle appeared + overlay badge
```

Streaming mode captures with sounddevice too (`use_microphone=False`) and hands int16 PCM to `AudioToTextRecorder.feed_audio()` so the same Gain applies.

**Never put blocking operations in `audio_callback` — it runs on a real-time thread.** (File I/O for gain persistence happens on the keyboard thread, not the audio thread.)

---

## Key tuning constants (`config.py` → `Settings`)

```python
device = "BlackHole 2ch"
silence_threshold = 0.03     # RMS; intentionally high to filter crowd noise    (--threshold)
post_speech_silence = 0.3    # silence that triggers transcription              (--silence)
min_speech = 0.3             # shorter utterances are ignored                    (--min-speech)
max_speech = 5.0             # force-flush for continuous commentary             (--max-speech)
max_partial_chars = 80       # streaming: cap partial text to avoid overflow
subtitle_seconds = 6.0       # auto-clear timer; keep > max_speech               (--subtitle-seconds)
screen = 1                   # 0 = main, 1 = external                            (--screen)
gain = 1.0                   # input gain, 0..5                                  (--gain, +/- keys)
highlight_cooldown = 10.0    # seconds before the same event fires again
```

---

## Known issues / gotchas

- **Whisper hallucination**: Crowd noise and BGM cause repeated words or symbol-only output. VAD mode filters via `no_speech_prob > 0.5`, `is_hallucination()` and `looks_like_prompt_echo()` (Whisper sometimes parrots the `initial_prompt` on silence). Streaming mode only applies the prompt-echo check (VAD is delegated to RealtimeSTT/Silero).
- **Repetition is not always word-level** (#31): Whisper emits cycles with no separator ("Would it beWould it be…"),
  so `split()` yields `["Would", "it", "beWould", …]` and no four tokens are ever equal. `_is_cyclic()` compares
  characters (spaces removed, shortest period via the KMP prefix function) and accepts a partial final cycle,
  because a chunk cut mid-hallucination ends in one. It needs 16+ characters and 4+ cycles before judging:
  "Ole, ole, ole!" and "Goal! Goal! Goal!" are periodic and real. Verified against a real session's 4854 lines —
  12 flagged, all genuine.
- **`_BOILERPLATE` costs one subtitle at full time**: "thanks for watching" is Whisper training-data boilerplate
  *and* something a commentator says when signing off. Dropping that one line is cheaper than letting sign-off
  text appear over live play, but do not extend the list with phrases that occur during a match.
- **`looks_like_prompt_echo()` only fires on a *run* of prompt text** (5+ words, or 12+ characters for CJK).
  A plain substring test would drop real commentary, because "free kick", "own goal" and every player name
  are prompt substrings as well as things commentators actually say (#26). The trade-off is that a very short
  echo ("Football commentary.") can slip through — one stray subtitle beats losing every "Free kick."
  That stray subtitle also reaches `highlights.handle()`, so "penalty, corner kick." can fire an event.
  Do **not** "fix" that by gating highlights on prompt membership: penalty, corner kick, own goal and VAR
  are prompt terms *and* real events, so it would suppress most true positives. The per-event cooldown
  already caps it at one marker per event per window.
- **Word counting is Unicode-aware on purpose** (`_NON_WORD_RE = [\W_]+`). An ASCII-only class turns every
  accented letter into a separator, so "Darwin Núñez, Luis Díaz" normalises to six tokens, crosses the
  5-word threshold and gets dropped as an echo. Squad lists are full of diacritics; keep `\w`.
- **CJK languages** use a 2-character minimum in `is_hallucination()` (`Settings.min_alpha_chars()`) so short words like `ゴール` are not dropped.
- **Term corrections must be anchored on context, not on the mis-heard word** (#32): a `max_speech` cut clips
  the final consonant, and `"card"` becomes `"car"` — an ordinary English word. `_CORRECTIONS_EN` therefore
  matches `"(yellow|red) car/cart"`, never `"car"` alone, and `"upside position"`, never `"upside"`. Corrections
  run before `highlights.handle()`, so fixing one also recovers the event marker. Synonyms are *not* corrections:
  `"extra time"` (the 30 minutes in a knockout) and `"added time"` are correct football English and are left alone.
- **`initial_prompt` on short chunks**: a short chunk (1-2 s) with a long prompt can increase prompt echoes; keep `FOOTBALL_TERMS_*` short. `--no-vocab` disables it.
- **Player-name fuzzy correction only handles Latin script** (`_WORD_RE` in `vocabulary.py`); Japanese names are only boosted via the prompt.
- **Fuzzy matching misses surname-only mis-hearings**: `name_cutoff = 0.8`, but "Sacker" scores only 0.6 against "Saka", and windows under 4 characters are not fuzzy-matched at all. Use an alias (`Saka=Sacker|Sarker`) — aliases are matched exactly, so they bypass both limits. They never enter the prompt (they are wrong spellings by definition).
- **Aliases replace conservatively**: a surname alias never invents a first name ("Sacker" → "Saka", not "Bukayo Saka") and never repeats one already present ("Kai Havits" → "Kai Havertz"). See `Vocabulary._fit_replacement()`.
- **A long `--players-file` can overflow the prompt**: Whisper's `initial_prompt` holds ~224 tokens; a full 25-man squad plus the football terms is already ~150-180. Two squads will be silently truncated — list one team, or just the players on the ball.
- **`silence_threshold` sensitivity**: Optimal value varies by environment. Too low increases hallucinations. Runtime gain (`+`/`-`) effectively shifts it.
- **`max_speech` is the primary segmentation mechanism, not a safety net** (#30). Commentary runs continuously,
  so `post_speech_silence` rarely fires. Cutting at exactly `max_speech` cuts mid-word and Whisper rejects *both*
  halves (empty / `no_speech`), so a long sentence produces no subtitle at all — measured 62% rejects in a real
  session. `chunking.split_for_flush()` cuts at the quietest 50 ms block in the last 0.6 s instead, and carries
  the last 0.3 s into the next buffer when even that block is above `silence_threshold`. Two invariants it must
  keep: the carry-over never exceeds **a third of the buffer** (it is re-transcribed, so it taxes the flush rate —
  fixed 0.6 s / 0.3 s windows against a 1.0 s buffer left only 0.25 s of new audio per flush, four Whisper calls
  per second of audio, and an `audio_queue` that grows without bound), and both pieces are **copies**, because the
  callback keeps concatenating into its buffer while the chunk sits in the queue.
- **A shorter `max_speech` is not cheaper.** Whisper pads every input to 30 s, so cost per chunk is flat
  (medium.en: ~0.8 s for a 1.5 s *or* a 6 s chunk). Shortening it costs *more* GPU time and fragments more.
  The defaults (`5.0` / `--silence 0.3`) come from a measured 60 s trace: forced mid-word cuts 48% → 17%.
- **Fullscreen overlay** needs three things together (#33), not just the collection-behaviour flags:
  `NSApplicationActivationPolicyAccessory` (a regular Dock app is not treated as an overlay utility),
  `CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle` at `NSScreenSaverWindowLevel`, and re-applying
  them afterwards. `Stationary` must **not** be set — Apple documents it as keeping the window "visible and
  stationary, like the desktop window", which pins the bar to the desktop Space. Qt's own default after
  `show()` is `FullScreenPrimary`, so whenever Qt recreates the native NSWindow the fix is silently undone;
  `OverlayApp._watch_overlay()` re-asserts the value every 2 s and on `screenChanged`, and both
  `make_visible_over_fullscreen()` and `macos.reapply_if_reverted()` read the behaviour back afterwards
  and return False on a mismatch instead of logging a success they did not verify. Three consequences
  worth keeping: the watchdog is installed even when the *first* attempt fails (a failed attempt is the
  case it exists for — it is only skipped when `macos.pyobjc_available()` says nothing will ever work);
  the `screenChanged` hook is re-attached whenever `windowHandle()` changes, because a recreated QWindow
  orphans the old connection; and a repair that AppKit refuses is logged once per distinct state
  (`macos._LogOnce`), not every 2 s forever.
- **Keyboard control needs a TTY**: when stdin is not a terminal (launched from an IDE/launchd) gain can only be set with `--gain`.

---

## Logging

- Logs written to `transcriber.log` (`--log-file`) and stdout simultaneously. Root level INFO, `football_transcriber.*` at DEBUG.
- **Why no subtitles appeared** (#27): `InputMonitor` (`audio.py`) logs a WARNING every 20 s while nothing has been
  transcribed, naming the cause — idle stream, digital silence (routing), signal below `silence_threshold` (with the
  observed peak RMS and gain), or every result filtered out (with a per-reason count). Rejected transcriptions are
  logged individually at DEBUG with their reason (`no_speech` / `empty` / `hallucination` / `prompt_echo`), so
  `--log-file` shows what was discarded. A short badge also flashes in the overlay, because the terminal is usually
  not visible while watching. `note_block()`/`note_speech()` run on the real-time audio thread and only bump a
  counter — all logging happens on the monitor thread.
- **A diagnosis must be true of the numbers it prints.** Two traps in `InputMonitor._diagnose()`:
  `speech` counts *queued chunks*, only in vad mode, so it is not a proxy for "there was speech" — keying the
  "below threshold" branch on it printed "peak RMS 0.1200 < 0.030". And a reject may be counted in the window
  *after* the chunk was queued (and streaming never counts a chunk at all), so the filtered-out message names
  no chunk count. Start the monitor after `stream.start()`, or it reports a dead stream that was never opened.
- Highlight markers go to `highlights.log` (`--highlight-log`).
- Thread exception handler is in place for post-crash diagnosis.
