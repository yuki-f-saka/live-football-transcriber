import unittest

from football_transcriber.text_filters import is_hallucination, looks_like_prompt_echo


class HallucinationTests(unittest.TestCase):
    def test_symbols_only(self):
        self.assertTrue(is_hallucination("..."))
        self.assertTrue(is_hallucination("!"))
        self.assertTrue(is_hallucination("St-"))

    def test_repeated_words(self):
        self.assertTrue(is_hallucination("far far far far far"))
        self.assertTrue(is_hallucination("and then tell tell tell tell me"))

    def test_normal_commentary(self):
        self.assertFalse(is_hallucination("Salah cuts inside and shoots!"))
        self.assertFalse(is_hallucination("far far away"))


PROMPT_EN = (
    "Football commentary. Terms: offside, onside, through ball, hat-trick, free kick, "
    "penalty, corner kick, goalkeeper, midfielder, striker, VAR, clean sheet, "
    "counter-attack, stoppage time, own goal, Premier League. "
    "Players: David Raya, Ben White, Declan Rice, Bukayo Saka, Kai Havertz."
)
PROMPT_JA = (
    "サッカー実況。用語: オフサイド、スルーパス、ハットトリック、フリーキック、PK、"
    "コーナーキック、ゴールキーパー、ミッドフィルダー、ストライカー、VAR、アディショナルタイム。"
)


class PromptEchoTests(unittest.TestCase):
    def test_no_prompt_never_echoes(self):
        self.assertFalse(looks_like_prompt_echo("Football commentary. Terms: offside", None))
        self.assertFalse(looks_like_prompt_echo("anything at all here", ""))

    def test_parroted_prompt_is_dropped(self):
        self.assertTrue(looks_like_prompt_echo(PROMPT_EN, PROMPT_EN))
        self.assertTrue(looks_like_prompt_echo(
            "Terms: offside, onside, through ball, hat-trick, free kick.", PROMPT_EN))
        self.assertTrue(looks_like_prompt_echo(
            "Players: David Raya, Ben White, Declan Rice.", PROMPT_EN))

    def test_short_phrases_from_the_prompt_are_kept(self):
        # Issue #26: these are prompt substrings *and* ordinary commentary.
        for text in ("Free kick.", "Corner kick!", "Own goal.", "Clean sheet.",
                     "Stoppage time.", "Counter-attack.", "Premier League.",
                     "Declan Rice.", "Bukayo Saka!", "The goalkeeper."):
            with self.subTest(text=text):
                self.assertFalse(looks_like_prompt_echo(text, PROMPT_EN))

    def test_normal_commentary_is_kept(self):
        self.assertFalse(looks_like_prompt_echo("Saka drives forward on the right wing.", PROMPT_EN))
        self.assertFalse(looks_like_prompt_echo("What a goal for Arsenal!", PROMPT_EN))

    def test_japanese_term_kept_but_run_of_terms_dropped(self):
        self.assertFalse(looks_like_prompt_echo("オフサイド", PROMPT_JA))
        self.assertFalse(looks_like_prompt_echo("ゴールキーパー", PROMPT_JA))
        self.assertTrue(looks_like_prompt_echo(
            "オフサイド、スルーパス、ハットトリック、フリーキック", PROMPT_JA))


if __name__ == "__main__":
    unittest.main()
