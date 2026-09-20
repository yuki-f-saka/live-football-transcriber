# Architecture — how audio becomes a subtitle

This document describes the main processing flow of `live-football-transcriber`:
what happens between a sound leaving the broadcast and a line of text appearing
on the overlay bar. It is the reference for *why* a change is safe — the README
covers installation and usage, `CLAUDE.md` covers conventions.

---

## 1. Overview

The app is a single process with four cooperating threads. Audio is captured
from a virtual output device, cut into utterances, transcribed by Whisper,
cleaned up, and pushed to a Qt overlay window.

```
 Broadcast (browser / player)
        │  macOS Multi-Output Device
        ├───────────────► Speakers          (you hear it)
        └───────────────► BlackHole 2ch     (we capture it)
                                │
                          sounddevice.InputStream
                                │
                    ┌───────────┴────────────┐
                    │   vad mode             │  streaming mode
                    │   (mlx-whisper)        │  (RealtimeSTT)
                    └───────────┬────────────┘
                                │
                     text post-processing
                     (filters → vocabulary → highlights)
                                │
                          OverlayApp.text_queue
                                │
                     SubtitleWindow (PyQt6, always on top)
```

A fifth participant watches the whole chain: `InputMonitor` (`audio.py`) runs on
its own thread and, every 20 s in which no subtitle was produced, says *why* —
see §5.

Two backends implement the middle box and are **deliberately separate
implementations** (`transcriber.py`, `streaming_transcriber.py`). Everything
around them — settings, overlay, gain, vocabulary, highlights — is shared.

---

## 2. Startup flow

`football-transcriber [vad|streaming] [options]` → `cli.main()`:

1. `build_parser()` parses the flags. `--list-devices`, `--show-config` and
   `--save` short-circuit and exit before any model is loaded.
2. `settings_from_args()` builds a `Settings` (`config.py`) by layering
   **dataclass defaults < config file < CLI flags**. Only non-`None` flags
   override, so an unset flag never erases a saved value.
3. `parse_event_list()` validates `--highlights` early, so a typo fails in
   milliseconds instead of after a multi-minute model download.
4. `setup_logging()` attaches a stdout handler *and* a file handler, and
   installs a `threading.excepthook` so a crash on a worker thread is still
   readable in `transcriber.log` afterwards.
5. The chosen backend's `run(settings)` is imported **lazily** — `mlx_whisper`
   and `RealtimeSTT` take seconds to import, and `--help` must stay instant.

`Settings.resolved_model()` turns a short size (`small`) into the concrete
model for the mode and language: an mlx-community repo for `vad`, a
faster-whisper name for `streaming`, and the English-only `.en` variants only
when `language == "en"`.

---

## 3. The main loop — `vad` mode (recommended)

```
audio_callback  (CoreAudio real-time thread, 50 ms blocks)
   │  gain.apply()            multiply + clip, no allocation beyond the block
   │  rms > silence_threshold → speech?
   │  accumulate into VadState.speech_buffer
   │  monitor.note_block(rms) / note_speech()   counters only, never I/O
   │  flush on: post_speech_silence of silence, or max_speech of speech
   │               (the latter via chunking.split_for_flush → chunk + carry-over)
   ▼
audio_queue : Queue[np.ndarray | None]
   │
transcription_worker  (background thread)
   │  mlx_whisper.transcribe(chunk, initial_prompt=vocab.prompt)
   │  drop + count a reason: no_speech / empty / hallucination / prompt_echo
   │  vocab.correct(text)
   │  highlights.handle(text)
   ▼
OverlayApp.text_queue : Queue[tuple[kind, text]]
   │
_poll_text  (Qt timer on the GUI thread, every 50 ms)
   ▼
SubtitleWindow.show_text() / show_partial() / show_status()
```

### Utterance segmentation

The VAD is a plain RMS gate, not a neural one — cheap enough to run on the
real-time thread. Per 50 ms block:

| State | Condition | Action |
|---|---|---|
| speech | `rms > silence_threshold` | append block, reset the silence counter |
| speech, too long | buffer ≥ `max_speech` | flush at the quietest block near the end, carry the tail over (#30) |
| trailing silence | was speaking, now quiet | keep appending, count silence |
| end of utterance | silence ≥ `post_speech_silence` | flush if buffer ≥ `min_speech`, else discard |

`silence_threshold` is intentionally high (0.03): the goal is to reject crowd
noise, not to catch every whisper. `max_speech` exists because continuous
commentary may never produce a real pause — and because of that it is the
*primary* segmentation mechanism, not a safety net. Cutting at exactly
`max_speech` cuts mid-word, and Whisper rejects both halves as empty or
no_speech, so the sentence disappears entirely. `chunking.split_for_flush()`
therefore cuts at the quietest 50 ms block in the last 0.6 s, and when even
that block is above the threshold it carries the last 0.3 s into the next
buffer so the broken word is whole in one of the two chunks (#30).

### The real-time rule

**`audio_callback` runs on CoreAudio's real-time thread. Nothing in it may
block.** No file I/O, no locks, no logging in the hot path beyond a warning on
stream status. `Gain` is a bare float (assignment is atomic under the GIL), so
the keyboard thread can change it without a lock. Persisting the gain to disk
happens on the keyboard thread, never here.

---

## 4. The main loop — `streaming` mode

RealtimeSTT owns the segmentation (Silero VAD) and runs two models: a small one
for partial text while the speaker is still talking, and a larger one for the
final result.

```
audio_callback (real-time thread)
   │  gain.apply() → int16 PCM
   ▼
recorder.feed_audio()            (use_microphone=False: we capture, not RealtimeSTT)
   ├─► on_realtime_transcription_update → push_partial(last max_partial_chars)
   └─► recorder.text()  (recorder_loop thread)
          │  looks_like_prompt_echo → drop
          │  vocab.correct() → push_final() → highlights.handle()
          ▼
       same text_queue → same SubtitleWindow
```

Partial text does **not** start the auto-clear timer; a final line does. The
partial is truncated to its trailing `max_partial_chars` characters so a long
sentence cannot overflow the bar.

Note the asymmetry with `vad` mode: only the prompt-echo filter runs here,
because `no_speech_prob` and the hallucination heuristic are not available —
VAD is delegated to Silero.

---

## 5. Text post-processing

Applied in this order to every finalized transcript:

1. **`is_hallucination(text, min_alpha_chars)`** (`text_filters.py`) — rejects
   four classic Whisper-on-noise failures: symbol-only output (`"..."`, `"!"`),
   the same word repeated four times in a row, *any* unit repeated four times
   at character level (`"Would it beWould it be..."` — the cycle boundary is
   not a space, so `split()` cannot see it, #31), and known training-data
   boilerplate (`"we'll see you next time"`, `"subtitles by ..."`), which is
   neither repetitive nor a prompt echo. CJK languages use a 2-character
   minimum instead of 4, so `ゴール` survives.

   The character check needs 16+ characters and 4+ cycles before it judges
   anything: "Goal! Goal! Goal!" and "Ole, ole, ole!" are periodic too. Over
   4854 accepted lines of a real session it flags 12, all genuine.
2. **`looks_like_prompt_echo(text, prompt)`** — on silence Whisper sometimes
   emits its own `initial_prompt` back. The test is a *run* of prompt text
   (5+ words, or 12+ characters for CJK), not bare containment: "free kick",
   "own goal" and every player name are prompt substrings *and* things
   commentators say, so a containment test drops real speech (#26). Word
   counting runs on Unicode-aware tokens, or accented squad names would split
   into extra tokens and cross the threshold by themselves.
3. **`Vocabulary.correct(text)`** (`vocabulary.py`) — regex normalisation of
   football terms (`"off side"` → `"offside"`, case preserved), then player-name
   correction: longest phrase first, exact aliases before fuzzy matching, and
   only on windows that start with a capitalised word (so `salad` never becomes
   `Salah`). Aliases exist because fuzzy matching misses surname-only
   mis-hearings; `Saka=Sacker` is matched exactly and bypasses the cutoff.

   Every term correction is anchored on a word that makes the phrase wrong, not
   on the mis-heard word itself: `"yellow car"` → `"yellow card"` (#32), while
   `"the car is parked"` is left alone. Corrections run *before*
   `HighlightDetector.handle()`, so fixing the text can also recover an event
   marker — but only for events that are switched on: `yellow_card` is not in
   `DEFAULT_EVENTS`, and the plural form (`"red cars"` → `"red cards"`) does not
   match the `red_card` pattern, which anchors on the singular.
4. **`HighlightDetector.handle(text)`** (`highlights.py`) — matches the text
   against per-event regexes (English + Japanese), applies a per-event cooldown
   so `"GOAL! GOAL! GOAL!"` fires once, then runs the configured actions:
   append a timestamped marker to `highlights.log`, post a macOS notification,
   play a sound.

The same `Vocabulary` instance also supplies the Whisper `initial_prompt`.
That prompt is capped in practice by Whisper's ~224-token limit, which is why a
two-squad `--players-file` is silently truncated.

Every drop above is counted by reason and logged at DEBUG, because an empty
overlay has several causes that look identical in a quiet log. `InputMonitor`
turns those counters into one sentence every 20 s — dead stream, digital
silence (routing), level below `silence_threshold`, utterances shorter than
`min_speech`, everything filtered out, or nothing came back — plus a short
badge in the overlay, since the terminal is not visible while watching a match.
Each branch is guarded so that it can only be chosen when the window's numbers
actually support it (#27).

---

## 6. Overlay and the macOS window server

`SubtitleWindow` (`overlay.py`) is a frameless, translucent, click-through
`QWidget`: `WindowTransparentForInput` plus `WA_ShowWithoutActivating` means it
never takes focus — which is also why runtime control reads keys from the
terminal (`KeyboardController`) instead of from the window.

Qt's `WindowStaysOnTopHint` only wins within the *same* Space, so a fullscreen
video player still covers the bar. Floating above *another app's* fullscreen
Space needs three things together (#33), and `macos.py` reaches past Qt with
PyObjC to do all three:

1. **`NSApplicationActivationPolicyAccessory`** — a regular Dock app is not
   treated as an overlay utility by the window server.
2. **`CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle`** at
   `NSScreenSaverWindowLevel`, click-through and not hidden on deactivate.
   `Stationary` must **not** be set: Apple documents it as keeping the window
   "visible and stationary, like the desktop window", which pins the bar to the
   desktop Space — the original symptom.
3. **Re-applying them.** Qt recreates the native `NSWindow` on some screen and
   Space changes, resetting the behaviour to its own `FullScreenPrimary`
   default and undoing the fix with nothing in the log.

`OverlayApp._watch_overlay()` is that third part: every 2 s and on
`screenChanged`, it re-attaches the signal if `windowHandle()` changed (a
recreated QWindow orphans the old connection) and calls
`macos.reapply_if_reverted()`. The watchdog is installed even when the *first*
attempt fails — a failed attempt is what it exists for — and is skipped only
when `macos.pyobjc_available()` says the bindings are missing entirely, in
which case the bar degrades to an ordinary always-on-top window.

Both `make_visible_over_fullscreen()` and `reapply_if_reverted()` read the
behaviour back from AppKit afterwards and return `False` on a mismatch, rather
than logging a success they did not verify. A repair AppKit keeps refusing is
reported once per distinct state (`macos._LogOnce`), not every 2 s forever.

> This is the one part of the flow that rests on undocumented window-server
> behaviour, which is why every step of it is verified and logged.

---

## 7. Invariants worth protecting

These are the properties a change must not break. Some are covered by tests,
some can only be checked by review — they are listed here so a reviewer knows
what to look for.

| Invariant | Enforced by |
|---|---|
| `audio_callback` never blocks (no I/O, no locks) | review — see §3 |
| Unity gain is a no-op on the audio path (no copy) | `tests/test_audio.py` |
| Settings precedence: defaults < file < flags | `tests/test_config.py`, `tests/test_cli.py` |
| `save_key()` does not clobber other keys in the file | `tests/test_config.py` |
| Short-size → concrete model mapping per mode/language | `tests/test_language.py` |
| Hallucination / prompt-echo filters do not eat real text | `tests/test_text_filters.py`, `tests/test_vocabulary.py` |
| Aliases never invent or duplicate a first name | `tests/test_vocabulary.py` |
| Highlight cooldown fires an event once per window | `tests/test_highlights.py` |
| Overlay collection behaviour excludes `Stationary` | `tests/test_macos.py` |
| A permanent repair failure is logged once, not every tick | `tests/test_macos.py` |
| A diagnosis is only chosen when the window's numbers support it | `tests/test_audio.py` |
| A change to one backend is mirrored in the other where shared | review |

The test suite is pure Python: no audio device, no GPU, no display. Anything
touching CoreAudio, Metal or the window server is exercised by running the app.

---

## 8. Quality gates

`ruff check .`, `mypy` and `pytest`, locally and in CI on every push and pull
request. Because CI runs on Linux, it covers the pure-Python logic above and
none of the platform layer — that is verified on the machine it runs on.

See [`QUALITY.md`](QUALITY.md).
