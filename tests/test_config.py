import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_transcriber.config import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_resolve_models(self):
        s = Settings()
        self.assertEqual(s.resolved_model(), "mlx-community/whisper-small.en-mlx")
        s = Settings(mode="streaming")
        self.assertEqual(s.resolved_model(), "small.en")
        self.assertEqual(s.resolved_realtime_model(), "tiny.en")

    def test_short_and_full_model_names(self):
        self.assertEqual(Settings(model="tiny").resolved_model(), "mlx-community/whisper-tiny.en-mlx")
        self.assertEqual(Settings(model="org/custom").resolved_model(), "org/custom")
        self.assertEqual(Settings(mode="streaming", model="medium.en").resolved_model(), "medium.en")

    def test_load_applies_file_then_overrides(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"screen": 0, "font_size": 44, "unknown_key": 1}))
            s = Settings.load(path, font_size=20)
            self.assertEqual(s.screen, 0)         # from file
            self.assertEqual(s.font_size, 20)     # override wins
            self.assertEqual(s.config_path, path)

    def test_save_and_save_key_roundtrip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            s = Settings(screen=0, config_path=path)
            s.save()
            self.assertEqual(json.loads(path.read_text())["screen"], 0)
            s.save_key("font_size", 12)
            data = json.loads(path.read_text())
            self.assertEqual(data["screen"], 0)      # untouched
            self.assertEqual(data["font_size"], 12)
            self.assertNotIn("config_path", data)


if __name__ == "__main__":
    unittest.main()
