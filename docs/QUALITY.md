# Quality gates

Three checks define "green" for this repo. They are configured in
`pyproject.toml` — not in CI — so a local run and a CI run are the same run.

```bash
pip install -e ".[dev]"

ruff check .    # lint
mypy            # type check
pytest          # unit tests
```

`.github/workflows/ci.yml` runs exactly these three on every push to `main` and
on every pull request, on Linux with Python 3.10 (the `requires-python` floor)
and 3.12 (what development uses).

---

## ruff

Configured at `line-length = 120` — the width the code was already written to —
with `E`/`W` (pycodestyle), `F` (pyflakes), `I` (import order), `UP`
(pyupgrade), `B` (bugbear), `SIM`, `C4` and `RUF`.

`target-version = "py310"` is what actually keeps the source compatible with the
oldest supported Python; see the mypy section for why that job is not mypy's.

The ambiguous-unicode rules (`RUF001`–`RUF003`) are **off**. `vocabulary.py` and
`highlights.py` are full of CJK text and full-width punctuation on purpose, so
those rules produce nothing but false positives here.

### `ruff format` is not enforced

Deliberately, for now. The repo predates it: enabling it rewrites roughly 400
lines of existing code, which is a diff nobody can review next to a real change.
Turn it on in its own commit, by adding a step to the workflow:

```yaml
- name: Format (ruff)
  run: ruff format --check .
```

Run `ruff format .` in the same commit and nothing else, so the reformat stays
reviewable as a pure no-op.

---

## mypy

Checks `football_transcriber/` only (not `tests/`), with `check_untyped_defs`
so function bodies without annotations are still analysed.

**`platform = "darwin"` is pinned.** The app only ever runs on macOS, and
without this the Linux CI runner would quietly skip every `sys.platform ==
"darwin"` branch — that is, most of the code that can actually break.

**`python_version` is deliberately *not* pinned.** Pinning it to the 3.10 floor
makes mypy parse the *installed* numpy stubs as 3.10 too, and current numpy
writes PEP 695 `type` statements in them; CI died inside `numpy/__init__.pyi`
before reaching any of our code. Ruff's `target-version` covers the syntax
compatibility that the pin was there for.

### Adding a dependency without type information

Audio, ML and Cocoa bindings ship no stubs, and the macOS-only ones are not
installed on the runner at all. They are listed once:

```toml
[[tool.mypy.overrides]]
module = ["sounddevice.*", "mlx_whisper.*", "RealtimeSTT.*", "AppKit.*", "objc.*"]
ignore_missing_imports = true
```

Add new ones to that list rather than scattering `# type: ignore` at each import
site — `warn_unused_ignores` is on, so stale per-line ignores become errors when
a library later ships stubs, and a list in one place is easy to re-check.

---

## pytest

The suite is pure Python: no audio device, no GPU, no display. That is what lets
it run on a Linux container in under a second, and it is also its limit.

| Covered by tests | Only verifiable by running the app on the Mac |
|---|---|
| settings precedence, model resolution | CoreAudio capture from BlackHole |
| hallucination and prompt-echo filters | mlx-whisper on the Metal GPU |
| term and player-name corrections, aliases | the overlay's Space / fullscreen behaviour |
| highlight patterns and cooldown | end-to-end latency and VAD tuning |
| gain arithmetic and clipping | |
| the overlay's intended collection behaviour | whether AppKit honours it |
| which diagnosis the monitor picks for a window | the numbers that reach it |

[`ARCHITECTURE.md`](ARCHITECTURE.md) §7 lists the invariants a change must not break and maps
each one to the test that covers it — or marks it review-only, because some
(the real-time rule for `audio_callback`, keeping the two backends in step)
cannot be expressed as a test at all.

---

## CI

One job, matrixed over the two Python versions:

- `libportaudio2` is installed from apt because `sounddevice` loads PortAudio at
  import time and the tests import it.
- `mlx-whisper` and `pyobjc` are marked `sys_platform == "darwin"` in
  `pyproject.toml`, so pip simply skips them on the runner. Nothing in CI needs
  them; nothing in CI can verify them either.
- `pull_request` workflows run from the merge ref (base + head), so a change to
  this workflow on `main` starts gating every open pull request immediately —
  including ones branched before it existed.
- `permissions: contents: read` — nothing in the job writes anything back, so
  it does not inherit the repository's default token scopes. Any step that
  later needs to comment or push must ask for that scope explicitly.
- `cancel-in-progress` applies to pull requests only. Superseding a run is
  right while a branch is being iterated on, but on `main` it would leave a
  commit whose only verdict is "cancelled" — and that verdict is what branch
  protection (below) would be checking.

---

## Keeping the tooling current

`ruff` and `mypy` are pinned to a feature series (`==0.16.*`, `==2.3.*`) rather
than floored. Both add diagnostics in minor releases, so a floating range means
an unrelated pull request can go red because of a rule that has nothing to do
with its diff. Bump the pin in its own commit, together with whatever the new
version flags — that way the noise lands once, on purpose, with a reviewer
looking at it.

---

## Where to tighten next

Roughly in order of value per unit of churn:

1. `ruff format --check`. Nothing blocks it now — pick a quiet moment, since
   the reformat touches almost every file.
2. `--strict` corners of mypy, module by module: `disallow_untyped_defs` is
   realistic for `config.py`, `vocabulary.py`, `highlights.py` and
   `text_filters.py`, which are already annotated.
3. Branch protection on `main` requiring the CI check, so the gate is not
   advisory.
4. Coverage on the pure-Python modules, if a number turns out to be worth
   having. The gap is known and written down in the table above, so a
   percentage would mostly re-state it.
