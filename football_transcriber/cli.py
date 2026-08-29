"""Command-line entry point: ``football-transcriber [vad|streaming] [options]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG_PATH, Settings


def _csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="football-transcriber",
        description="Real-time speech-to-text subtitle overlay for live football broadcasts (macOS).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "mode", nargs="?", choices=["vad", "streaming"], default=None,
        help="vad = VAD chunking + mlx-whisper (Metal GPU, recommended); "
             "streaming = RealtimeSTT with live partial text (default: vad)",
    )

    g = p.add_argument_group("audio / model")
    g.add_argument("--device", help="input device name substring (default: BlackHole 2ch)")
    g.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    g.add_argument("--model", help="model size (tiny/base/small/medium/large) or full model name; "
                                   "English uses the faster '.en' variants automatically (default: small, ja: medium)")
    g.add_argument("--realtime-model", help="[streaming] model for partial updates (default: tiny.en)")
    g.add_argument("--lang", dest="language", help="transcription language code, e.g. en, ja (ja switches to multilingual models)")
    g.add_argument("--gain", type=float,
                   help="input gain multiplier (0 = mute .. 5.0); adjustable at runtime with +/- keys")

    g = p.add_argument_group("VAD tuning (vad mode)")
    g.add_argument("--threshold", dest="silence_threshold", type=float,
                   help="RMS level treated as silence (higher filters more crowd noise)")
    g.add_argument("--silence", dest="post_speech_silence", type=float,
                   help="seconds of silence after speech that triggers transcription")
    g.add_argument("--min-speech", dest="min_speech", type=float, help="ignore utterances shorter than this (s)")
    g.add_argument("--max-speech", dest="max_speech", type=float, help="force-flush after this many seconds")

    g = p.add_argument_group("vocabulary")
    g.add_argument("--no-vocab", dest="vocabulary", action="store_false", default=None,
                   help="disable the football prompt hints and text corrections")
    g.add_argument("--players", type=_csv_list,
                   help="comma-separated player/team names to boost and auto-correct, e.g. 'Salah,Haaland,De Bruyne'")
    g.add_argument("--players-file", dest="players_file", help="file with one player name per line")

    g = p.add_argument_group("highlights")
    g.add_argument("--highlights", type=_csv_list, metavar="EVENTS",
                   help="detect match events from the transcript: comma list of "
                        "goal,penalty,red_card,yellow_card,var,offside,free_kick,corner,substitution or 'all'")
    g.add_argument("--highlight-log", dest="highlight_log", help="file to append timestamped event markers to")
    g.add_argument("--notify", dest="highlight_notify", action="store_true", default=None,
                   help="show a macOS notification for each detected event")
    g.add_argument("--highlight-sound", dest="highlight_sound", help="audio file to play (afplay) on each event")
    g.add_argument("--highlight-cooldown", dest="highlight_cooldown", type=float,
                   help="seconds before the same event may fire again")

    g = p.add_argument_group("overlay")
    g.add_argument("--screen", type=int, help="screen index to show the overlay on (0 = main)")
    g.add_argument("--font-size", dest="font_size", type=int)
    g.add_argument("--subtitle-seconds", dest="subtitle_seconds", type=float, help="auto-clear delay")
    g.add_argument("--width", dest="window_width_ratio", type=float, help="bar width as fraction of screen")
    g.add_argument("--margin", dest="screen_margin_y", type=int, help="px from top of screen")
    g.add_argument("--no-fullscreen", dest="fullscreen_overlay", action="store_false", default=None,
                   help="do not force the overlay above fullscreen apps / all Spaces")

    g = p.add_argument_group("config")
    g.add_argument("--config", type=Path, default=None, help=f"config file (default: {DEFAULT_CONFIG_PATH})")
    g.add_argument("--save", action="store_true", help="save the effective settings to the config file and exit")
    g.add_argument("--show-config", action="store_true", help="print the effective settings and exit")
    g.add_argument("--log-file", dest="log_file", help="log file path")
    return p


def settings_from_args(args: argparse.Namespace) -> Settings:
    overrides = {
        k: v for k, v in vars(args).items()
        if k not in {"config", "save", "show_config", "list_devices"} and v is not None
    }
    return Settings.load(args.config, **overrides)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_devices:
        from .audio import list_input_devices
        for i, name in list_input_devices():
            print(f"  {i}: {name}")
        return 0

    settings = settings_from_args(args)
    try:
        from .highlights import parse_event_list
        parse_event_list(settings.highlights)
    except ValueError as e:
        parser.error(str(e))

    if args.show_config:
        import json
        print(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.save:
        path = settings.save()
        print(f"Saved settings to {path}")
        return 0

    from .app import setup_logging
    setup_logging(settings)

    if settings.mode == "streaming":
        from .streaming_transcriber import run
    else:
        from .transcriber import run
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
