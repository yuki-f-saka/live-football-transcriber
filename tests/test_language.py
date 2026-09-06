import unittest

from football_transcriber.config import Settings
from football_transcriber.text_filters import is_hallucination


class LanguageModelTests(unittest.TestCase):
    def test_english_defaults(self):
        self.assertEqual(Settings().resolved_model(), "mlx-community/whisper-small.en-mlx")
        s = Settings(mode="streaming")
        self.assertEqual((s.resolved_model(), s.resolved_realtime_model()), ("small.en", "tiny.en"))

    def test_japanese_switches_to_multilingual(self):
        s = Settings(language="ja")
        self.assertEqual(s.resolved_model(), "mlx-community/whisper-medium-mlx")  # ja defaults to medium
        self.assertEqual(Settings(language="ja", model="small").resolved_model(), "mlx-community/whisper-small-mlx")
        self.assertEqual(Settings(language="ja", model="large").resolved_model(), "mlx-community/whisper-large-v3-mlx")
        s = Settings(mode="streaming", language="ja", model="small")
        self.assertEqual((s.resolved_model(), s.resolved_realtime_model()), ("small", "tiny"))

    def test_explicit_names_pass_through(self):
        self.assertEqual(Settings(language="ja", model="org/x").resolved_model(), "org/x")
        self.assertEqual(Settings(mode="streaming", model="medium.en").resolved_model(), "medium.en")
        self.assertEqual(Settings(mode="streaming", model="large-v3").resolved_model(), "large-v3")
        # ".en" size given for a non-English language still maps sensibly for vad mode
        self.assertEqual(Settings(model="small.en").resolved_model(), "mlx-community/whisper-small.en-mlx")

    def test_cjk_hallucination_threshold(self):
        self.assertEqual(Settings(language="ja").min_alpha_chars(), 2)
        self.assertEqual(Settings().min_alpha_chars(), 4)
        self.assertFalse(is_hallucination("ゴール", 2))   # 3 chars: valid Japanese
        self.assertTrue(is_hallucination("ゴール", 4))    # would be dropped with the English threshold
        self.assertTrue(is_hallucination("。", 2))


if __name__ == "__main__":
    unittest.main()
