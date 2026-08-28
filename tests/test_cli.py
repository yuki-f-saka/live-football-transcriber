import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_transcriber.cli import build_parser, settings_from_args


class CliTests(unittest.TestCase):
    def test_defaults(self):
        with TemporaryDirectory() as tmp:
            args = build_parser().parse_args(["--config", str(Path(tmp) / "c.json")])
            s = settings_from_args(args)
            self.assertEqual(s.mode, "vad")
            self.assertEqual(s.language, "en")
            self.assertEqual(s.screen, 1)

    def test_flags_map_to_settings(self):
        with TemporaryDirectory() as tmp:
            argv = ["streaming", "--model", "small", "--screen", "0", "--silence", "0.6",
                    "--threshold", "0.05", "--config", str(Path(tmp) / "c.json")]
            s = settings_from_args(build_parser().parse_args(argv))
            self.assertEqual(s.mode, "streaming")
            self.assertEqual(s.model, "small")
            self.assertEqual(s.screen, 0)
            self.assertEqual(s.post_speech_silence, 0.6)
            self.assertEqual(s.silence_threshold, 0.05)


if __name__ == "__main__":
    unittest.main()
