import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from football_transcriber.highlights import HighlightDetector, parse_event_list


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.d = HighlightDetector(events=parse_event_list("all"))

    def test_goal_variants(self):
        for t in ["What a goal!", "Haaland scores", "and it's 2-1", "the equaliser", "hat-trick hero", "ゴール！"]:
            self.assertIn("goal", self.d.detect(t), t)

    def test_goal_kick_and_goalkeeper_do_not_fire(self):
        self.assertNotIn("goal", self.d.detect("goal kick for City"))
        self.assertNotIn("goal", self.d.detect("the goalkeeper gathers"))

    def test_other_events(self):
        self.assertEqual(self.d.detect("that's a penalty and a red card"), ["penalty", "red_card"])
        self.assertIn("var", self.d.detect("VAR is checking"))
        self.assertIn("yellow_card", self.d.detect("he's been booked"))
        self.assertIn("offside", self.d.detect("flag is up, offside"))
        self.assertEqual(self.d.detect("nothing happening here"), [])


class HandleTests(unittest.TestCase):
    def test_cooldown_and_log_marker(self):
        now = [100.0]
        seen = []
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "hl.log"
            d = HighlightDetector(events=["goal"], cooldown=10, log_path=path,
                                  on_event=lambda e, t: seen.append(e), clock=lambda: now[0])
            self.assertEqual(d.handle("Goal!"), ["goal"])
            now[0] += 5
            self.assertEqual(d.handle("GOAL GOAL"), [])        # within cooldown
            now[0] += 6
            self.assertEqual(d.handle("scores again"), ["goal"])
            self.assertEqual(seen, ["goal", "goal"])
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("(+00:00) ⚽ GOAL: Goal!", lines[0])
            self.assertIn("(+00:11) ⚽ GOAL: scores again", lines[1])

    def test_disabled(self):
        d = HighlightDetector(events=[])
        self.assertFalse(d.enabled)
        self.assertEqual(d.handle("Goal!"), [])


class ParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_event_list("goal, Red-Card,goal"), ["goal", "red_card"])
        self.assertEqual(parse_event_list(["goal,var", "penalty"]), ["goal", "var", "penalty"])
        self.assertEqual(parse_event_list(None), [])
        self.assertIn("substitution", parse_event_list("all"))
        with self.assertRaises(ValueError):
            parse_event_list("throw_in")


if __name__ == "__main__":
    unittest.main()
