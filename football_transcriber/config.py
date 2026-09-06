"""All tunable settings in one place.

Precedence (lowest → highest): dataclass defaults → config file → CLI flags.
The config file lives at ``~/.config/football-transcriber/config.json`` unless
overridden with ``--config``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("FOOTBALL_TRANSCRIBER_CONFIG")
    or Path.home() / ".config" / "football-transcriber" / "config.json"
)

# mlx-whisper (VAD mode) model repos, keyed by short size name
MLX_MODELS_EN = {
    "tiny": "mlx-community/whisper-tiny.en-mlx",
    "base": "mlx-community/whisper-base.en-mlx",
    "small": "mlx-community/whisper-small.en-mlx",
    "medium": "mlx-community/whisper-medium.en-mlx",
}


@dataclass
class Settings:
    # --- Mode / audio / model ---
    mode: str = "vad"                      # "vad" (mlx-whisper) or "streaming" (RealtimeSTT)
    device: str = "BlackHole 2ch"          # substring of the input device name
    sample_rate: int = 16000
    model: str | None = None               # short size ("tiny", "small", ...) or full model name; None = default for mode
    realtime_model: str | None = None      # streaming mode only: model for partial updates
    language: str = "en"

    # --- VAD (vad mode) ---
    silence_threshold: float = 0.03        # RMS below this is silence (high on purpose: filters crowd noise)
    post_speech_silence: float = 0.4       # seconds of silence after speech that triggers transcription
    min_speech: float = 0.3                # utterances shorter than this are ignored
    max_speech: float = 1.5                # force-flush after this many seconds of continuous speech

    # --- Streaming mode ---
    max_partial_chars: int = 80            # cap partial text to prevent overlay overflow

    # --- Overlay appearance ---
    font_size: int = 30
    font_color: str = "white"
    font_color_partial: str = "white"
    bg_color: str = "#111111"
    bg_opacity: int = 200                  # 0 (transparent) .. 255 (opaque)
    subtitle_seconds: float = 4.0          # auto-clear delay for finalized subtitle
    screen_margin_y: int = 40              # px from top of screen
    window_width_ratio: float = 0.65       # subtitle bar width as fraction of screen width
    screen: int = 1                        # 0 = main screen, 1 = first external monitor, ...

    # --- Logging ---
    log_file: str = "transcriber.log"

    # Internal: where this Settings was loaded from / will be saved to
    config_path: Path = field(default=DEFAULT_CONFIG_PATH, repr=False, compare=False)

    # ------------------------------------------------------------------
    def resolved_model(self) -> str:
        """Return the concrete model identifier for the active mode."""
        name = self.model
        if self.mode == "vad":
            if name is None:
                name = "small"
            if "/" in name:
                return name
            return MLX_MODELS_EN.get(name, f"mlx-community/whisper-{name}-mlx")
        # streaming (faster-whisper model names)
        if name is None:
            return "small.en"
        return name

    def resolved_realtime_model(self) -> str:
        return self.realtime_model or "tiny.en"

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("config_path", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any], **overrides: Any) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known and v is not None}
        clean.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**clean)

    @classmethod
    def load(cls, path: Path | None = None, **overrides: Any) -> "Settings":
        """Load from the config file (if present) and apply CLI overrides on top."""
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        settings = cls.from_dict(data, **overrides)
        settings.config_path = path
        return settings

    def save(self, path: Path | None = None) -> Path:
        """Write every setting to the config file (creating parent directories)."""
        path = Path(path) if path else self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    def save_key(self, key: str, value: Any, path: Path | None = None) -> Path:
        """Persist a single key without clobbering other values already in the file."""
        path = Path(path) if path else self.config_path
        data: dict[str, Any] = {}
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = {}
        data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path
