#!/usr/bin/env python3
"""Backward-compatible launcher: VAD + mlx-whisper mode.

Equivalent to ``football-transcriber vad``. All options are passed through,
e.g. ``python overlay_transcribe.py --screen 0 --lang ja``.
"""

import sys

from football_transcriber.cli import main

if __name__ == "__main__":
    sys.exit(main(["vad", *sys.argv[1:]]))
