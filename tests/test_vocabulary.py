import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_transcriber.text_filters import looks_like_prompt_echo
from football_transcriber.vocabulary import Vocabulary, load_players_file


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary("en", ["Salah", "Haaland", "De Bruyne", "Manchester City"])

    def test_term_normalisation(self):
        self.assertEqual(self.v.correct("that's off side"), "that's offside")
        self.assertEqual(self.v.correct("Off side flag is up"), "Offside flag is up")
        self.assertEqual(self.v.correct("a hat trick for him"), "a hat-trick for him")
        self.assertEqual(self.v.correct("the goal keeper saves"), "the goalkeeper saves")
        self.assertEqual(self.v.correct("freekicks and free-kicks"), "free kicks and free kicks")
        self.assertEqual(self.v.correct("the V.A.R. check"), "the VAR check")
        self.assertEqual(self.v.correct("in the premier league"), "in the Premier League")

    def test_player_fuzzy_match(self):
        self.assertEqual(self.v.correct("Harland scores!"), "Haaland scores!")
        self.assertEqual(self.v.correct("great run by Sala there"), "great run by Salah there")
        self.assertEqual(self.v.correct("De Brune with the pass"), "De Bruyne with the pass")
        self.assertEqual(self.v.correct("Manchester city are ahead"), "Manchester City are ahead")

    def test_lowercase_words_are_left_alone(self):
        # "salad" is close to "salah" but is not capitalised → not a name
        self.assertEqual(self.v.correct("he had a salad"), "he had a salad")
        self.assertEqual(self.v.correct("Haaland"), "Haaland")

    def test_disabled_is_identity(self):
        v = Vocabulary("en", ["Salah"], enabled=False)
        self.assertEqual(v.correct("off side Sala"), "off side Sala")
        self.assertIsNone(v.prompt)

    def test_prompt_contents(self):
        self.assertIn("offside", self.v.prompt)
        self.assertIn("Players: Salah, Haaland, De Bruyne, Manchester City.", self.v.prompt)
        ja = Vocabulary("ja", ["三笘"])
        self.assertIn("オフサイド", ja.prompt)
        self.assertIn("三笘", ja.prompt)

    def test_players_file(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "squad.txt"
            p.write_text("Salah  # LFC\n\n# comment\nHaaland\n")
            self.assertEqual(load_players_file(p), ["Salah", "Haaland"])


class PromptEchoTests(unittest.TestCase):
    def test_echo_detected(self):
        prompt = Vocabulary("en", ["Salah"]).prompt
        self.assertTrue(looks_like_prompt_echo("Football commentary. Terms: offside, onside", prompt))
        self.assertTrue(looks_like_prompt_echo("Players: Salah.", prompt))

    def test_real_text_passes(self):
        prompt = Vocabulary("en").prompt
        self.assertFalse(looks_like_prompt_echo("Salah cuts inside and scores", prompt))
        self.assertFalse(looks_like_prompt_echo("offside", prompt))  # too short to judge
        self.assertFalse(looks_like_prompt_echo("anything", None))


if __name__ == "__main__":
    unittest.main()
