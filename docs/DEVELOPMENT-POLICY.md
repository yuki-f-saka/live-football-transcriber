# Development policy — how much to read, and what the tools can cover

This is a solo project. Nobody else reviews the code, `/code-review` does the
first pass, and the goal is to keep the amount a human has to read as small as
it can honestly be. This document says how small that is, and why.

It is a policy, not a description: [`ARCHITECTURE.md`](ARCHITECTURE.md) says how
the app works, [`QUALITY.md`](QUALITY.md) says what the gates check.

---

## What the evidence says

The four pull requests reviewed on 2026-09-20 (#28, #29, #34, #35) produced
eight medium findings. Where they were is the whole argument:

| Kind | Count | Would CI have caught it? |
|---|---|---|
| Logic bug inside a **pure function** | 3 | No — but only because no test stated the case |
| **Wiring / platform layer** (start order, Cocoa, Qt) | 4 | No — structurally not runnable on the Linux runner |
| **Type error** | 1 | Yes (`mypy`, verified) |

Three of the eight were in `text_filters.py` and `audio.py._diagnose` — the two
most testable pieces of code in the repository. An ASCII-only normalisation
dropped real commentary containing accented player names; a diagnosis printed
`peak RMS 0.1200 < 0.030` and named the wrong flag. Both are pure functions,
both were trivially testable, and neither had a test for the case.

**The gap is not "code that cannot be tested". It is "a requirement nobody
stated".** Deterministic verification protects the regression of a requirement
that already exists. It cannot invent the requirement, and inventing it is the
part that needs someone — a person or a review agent — to look at the code and
think "what input makes this wrong?".

---

## The rule

**Read the review findings. Read the diff of the code CI cannot execute.
Nothing else.**

The second half is a short list, and it is the list to keep short:

| Must be read on change | Why |
|---|---|
| `audio_callback` bodies (`transcriber.py`, `streaming_transcriber.py`) | Real-time thread; a blocking call cannot be detected by any gate here |
| `macos.py` | Depends on undocumented window-server behaviour; PyObjC is absent in CI |
| `OverlayApp` wiring (`app.py`) | Qt signal/timer lifetimes; no display on the runner |
| Anything importing `sounddevice`, `mlx_whisper`, `RealtimeSTT`, `AppKit` | Not installed on the runner |

Roughly 300 of ~2000 lines. Everything else — `config.py`, `vocabulary.py`,
`text_filters.py`, `highlights.py`, `cli.py` — is pure and fully reachable from
`pytest`, so there a green suite is a real answer rather than a proxy for one.

For those pure modules the obligation is different, and it is the one the
evidence above is about: **when a finding lands in them, the fix ships with a
test that states the requirement.** That is what converts a one-off catch into
something the gates own from then on.

---

## What raises the floor, in order

1. **An offline input mode** (`--input-file recording.wav` instead of the
   capture device). This is the single highest-value change available: it makes
   the whole chain — VAD segmentation, the filters, vocabulary correction,
   highlight detection — runnable without an audio device, which moves most of
   the "wiring" row above into CI's reach. With a fake transcription backend it
   needs no Metal GPU either. It also makes VAD tuning measurable instead of
   hand-timed.
2. **Branch protection on `main` requiring the CI check.** Until this exists the
   gates are advisory and a red `main` is reachable. (`cancel-in-progress` is
   already scoped to pull requests so every `main` commit keeps a real verdict.)
3. **Keep [`ARCHITECTURE.md`](ARCHITECTURE.md) §7 honest.** Every invariant
   names either a test or "review". **The number of review-only rows is the
   metric** — it should fall over time. Merging #34 moved one row from review to
   `tests/test_macos.py`; that is what progress looks like.
4. **`ruff format`.** Consistency only. It catches no bugs, so it goes last.

---

## Branching

`main` plus **short-lived pull requests, merged within a day**.

Trunk-based (committing straight to `main`) is defensible for a solo project,
but not here, for one concrete reason: `/code-review` fires per pull request. It
is the mechanism that found all eight findings above. Removing the pull request
removes the hook and with it the only step that generates new requirements.

What must *not* happen again is the state of 2026-09-19: four pull requests open
in parallel for over a week. That pays the cost of branching (rebases, conflicts
— #35 had to be rebased across three merges) while getting none of its benefit.
The branch is a review hook, not a workspace.

---

## The honest limit

"A human reads nothing" is not reachable, and aiming at it means unstated
requirements stay unstated forever. The reachable target is **bounded** reading:
the findings list, plus the roughly 300 lines no gate can execute. That is a few
minutes per change, and it is already what happens in practice.

Everything in this document is a way of making that bound smaller — never a way
of pretending it is zero.
