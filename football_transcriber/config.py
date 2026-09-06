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

# mlx-whisper (VAD mode) model repos on HuggingFace, keyed by short size name.
# English-only ".en" variants are faster/more accurate for English; any other
# language needs the multilingual variants.
MLX_MODELS_EN = {
    "tiny": "mlx-community/whisper-tiny.en-mlx",
    "base": "mlx-community/whisper-base.en-mlx",
    "small": "mlx-community/whisper-small.en-mlx",
    "medium": "mlx-community/whisper-medium.en-mlx",
}
MLX_MODELS_MULTI = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
# Default model size per language. Japanese accuracy depends heavily on model
# size (tiny/small struggle with names), so it defaults to medium.
DEFAULT_SIZE = {"en": "small", "ja": "medium"}
DEFAULT_SIZE_OTHER = "small"

# Languages whose script is not space-delimited alphabetic text (affects the
# "too few letters" hallucination heuristic).
CJK_LANGUAGES = {"ja", "zh", "ko"}


@dataclass
class Settings:
    # --- Mode / audio / model ---
    mode: str = "vad"                      # "vad" (mlx-whisper) or "streaming" (RealtimeSTT)
    device: str = "BlackHole 2ch"          # substring of the input device name
    sample_rate: int = 16000
    model: str | None = None               # short size ("tiny", "small", ...) or full model name; None = default for mode
    realtime_model: str | None = None      # streaming mode only: model for partial updates
    language: str = "en"

    # --- Input gain (issue #2) — adjustable at runtime with +/- keys, persisted on change ---
    gain: float = 1.0

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
    fullscreen_overlay: bool = True        # show over fullscreen apps / all Spaces (needs PyObjC)

    # --- Vocabulary (issue #10) ---
    vocabulary: bool = True                # inject football terms into Whisper's initial_prompt + fix common mis-hearings
    players: list[str] = field(default_factory=list)   # player/team names to boost and auto-correct
    players_file: str | None = None        # text file with one name per line (per-match squad list)

    # --- Logging ---
    log_file: str = "transcriber.log"

    # Internal: where this Settings was loaded from / will be saved to
    config_path: Path = field(default=DEFAULT_CONFIG_PATH, repr=False, compare=False)

    # ------------------------------------------------------------------
    @property
    def is_english(self) -> bool:
        return self.language == "en"

    def default_size(self) -> str:
        return DEFAULT_SIZE.get(self.language, DEFAULT_SIZE_OTHER)

    def resolved_model(self) -> str:
        """Return the concrete model identifier for the active mode and language.

        ``model`` may be a short size ("tiny", "small", "medium", "large"), a
        faster-whisper name ("small.en"), or a full HuggingFace repo. Short
        sizes are mapped to English-only models for ``en`` and multilingual
        models otherwise.
        """
        name = self.model or self.default_size()
        if self.mode == "vad":
            if "/" in name:
                return name
            size = name.removesuffix(".en")
            table = MLX_MODELS_EN if (self.is_english and size in MLX_MODELS_EN) else MLX_MODELS_MULTI
            return table.get(size, f"mlx-community/whisper-{name}-mlx")
        # streaming (faster-whisper model names): "small" → "small.en" for English
        if "." in name or "/" in name or name.startswith("large") or name == "turbo":
            return name
        return f"{name}.en" if self.is_english else name

    def resolved_realtime_model(self) -> str:
        name = self.realtime_model or "tiny"
        if "." in name or "/" in name:
            return name
        return f"{name}.en" if self.is_english else name

    def min_alpha_chars(self) -> int:
        """Hallucination filter threshold: CJK packs more meaning per character."""
        return 2 if self.language in CJK_LANGUAGES else 4

    def player_names(self) -> list[str]:
        """Names from ``players`` plus ``players_file`` (if set), de-duplicated."""
        from .vocabulary import load_players_file
        names = list(self.players)
        if self.players_file:
            names.extend(load_players_file(self.players_file))
        seen: set[str] = set()
        out: list[str] = []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

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
