#!/usr/bin/env python3
"""Backward-compatible launcher: RealtimeSTT streaming mode.

Equivalent to ``football-transcriber streaming``. All options are passed through.
"""

import sys

from football_transcriber.cli import main

if __name__ == "__main__":
    sys.exit(main(["streaming", *sys.argv[1:]]))
