import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_transcriber.text_filters import looks_like_prompt_echo
from football_transcriber.vocabulary import Vocabulary, load_players_file, parse_player_spec


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


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.v = Vocabulary("en", [
            "Bukayo Saka=Saka|Sacker|Sarker",
            "Declan Rice=Rice|Rise",
            "Eze=Ez",
            "Myles Lewis-Skelly=Lewis Skelly",
            "Kai Havertz=Havits",
            "Ezri Konsa=Konser",
            "Martin Odegaard=Ode Guard",
        ])

    def test_spec_parsing(self):
        self.assertEqual(parse_player_spec("Bukayo Saka=Saka|Sacker"), ("Bukayo Saka", ["Saka", "Sacker"]))
        self.assertEqual(parse_player_spec("Declan Rice"), ("Declan Rice", []))
        self.assertEqual(parse_player_spec("  Kai Havertz  =  Havits | "), ("Kai Havertz", ["Havits"]))

    def test_alias_beats_the_fuzzy_cutoff(self):
        # "Sacker" scores 0.6 against "Saka" — below name_cutoff, so only an alias fixes it
        self.assertEqual(self.v.correct("Sacker takes the corner"), "Saka takes the corner")
        self.assertEqual(self.v.correct("great ball from Sarker"), "great ball from Saka")
        self.assertEqual(self.v.correct("Rise wins it back"), "Rice wins it back")

    def test_alias_shorter_than_the_fuzzy_minimum(self):
        # 2 characters: too short to fuzzy-match, but an exact alias still applies
        self.assertEqual(self.v.correct("Ez runs at them"), "Eze runs at them")

    def test_no_invented_or_duplicated_first_name(self):
        # a surname alias carries the full name, but must not add a first name
        # the commentator never said, nor repeat one already in the text
        self.assertEqual(self.v.correct("Sacker again"), "Saka again")
        self.assertEqual(self.v.correct("Kai Havits on the left"), "Kai Havertz on the left")
        self.assertEqual(self.v.correct("Ezra Konser heads it clear"), "Ezra Konsa heads it clear")
        self.assertEqual(self.v.correct("Myles Lewis Skelly overlaps"), "Myles Lewis-Skelly overlaps")

    def test_multi_token_alias(self):
        self.assertEqual(self.v.correct("Ode Guard with the pass"), "Martin Odegaard with the pass")

    def test_alias_token_count_may_differ_from_the_name(self):
        self.assertEqual(self.v.correct("Lewis Skelly overlaps"), "Myles Lewis-Skelly overlaps")

    def test_canonical_name_still_matches(self):
        self.assertEqual(self.v.correct("Bukayo Saka cuts inside"), "Bukayo Saka cuts inside")
        self.assertEqual(self.v.correct("Bukayo Sarker cuts inside"), "Bukayo Saka cuts inside")

    def test_aliases_stay_out_of_the_prompt(self):
        prompt = self.v.prompt
        self.assertIn("Players: Bukayo Saka, Declan Rice, Eze, Myles Lewis-Skelly, "
                      "Kai Havertz, Ezri Konsa, Martin Odegaard.", prompt)
        for wrong in ("Sacker", "Sarker", "Rise", "Lewis Skelly", "Havits", "Konser", "Ode Guard"):
            self.assertNotIn(wrong, prompt)

    def test_lowercase_words_are_still_left_alone(self):
        # an alias must not turn ordinary lowercase words into a name
        self.assertEqual(self.v.correct("boiled rice"), "boiled rice")
        self.assertEqual(self.v.correct("he had a salad"), "he had a salad")

    def test_aliases_are_exposed(self):
        self.assertEqual(self.v.aliases["Declan Rice"], ["Rice", "Rise"])
        self.assertEqual(self.v.players[0], "Bukayo Saka")

    def test_alias_specs_load_from_a_file(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "squad.txt"
            p.write_text("Bukayo Saka=Saka|Sacker   # 7\n\n# comment\nDeclan Rice\n")
            specs = load_players_file(p)
            self.assertEqual(specs, ["Bukayo Saka=Saka|Sacker", "Declan Rice"])
            v = Vocabulary("en", specs)
            self.assertEqual(v.correct("Sacker again"), "Saka again")


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
