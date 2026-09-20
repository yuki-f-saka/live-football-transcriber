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

    def test_repeated_phrase_without_spaces(self):
        """Issue #31: the cycle boundary is not a space, so split() cannot see it.

        "Would it be" * 70 tokenises as ["Would", "it", "beWould", "it", ...] —
        no four consecutive tokens are equal and the word-level check never
        fires, so ~70 repetitions reached the overlay.
        """
        self.assertTrue(is_hallucination("Would it be" * 70))
        self.assertTrue(is_hallucination("abcabcabcabcabcabcab"))

    def test_repeated_phrase_with_spaces(self):
        """A repeated *phrase* is invisible to a per-word comparison too."""
        self.assertTrue(is_hallucination("Nice carry. " * 6))
        self.assertTrue(is_hallucination("and Buck " * 8))

    def test_a_short_unit_has_to_repeat_more_before_it_is_a_hallucination(self):
        """A chant is a real thing a commentator does; a loop is not.

        Both are periodic, so length alone cannot separate them. A unit under
        _SHORT_UNIT_CHARS is chant-sized and needs six cycles; every repetition
        in the 4854-line reference log clears that (5 to 111 cycles).
        """
        for text in ("Come on, come on, come on, come on!",
                     "Go on, go on, go on, go on!",
                     "Yes, yes, yes, yes!"):
            with self.subTest(text=text):
                self.assertFalse(is_hallucination(text))
        self.assertTrue(is_hallucination("come on " * 7))

    def test_cjk_cycles_are_measured_on_a_shorter_text(self):
        """16 characters is a whole sentence in Japanese, not a loop.

        The CJK minimum mirrors min_alpha_chars: without it the cycle check
        never runs on ja at all. "ゴール" x4 is real commentary; x8 is not.
        """
        self.assertFalse(is_hallucination("ゴール" * 4, 2))
        self.assertTrue(is_hallucination("ゴール" * 8, 2))
        self.assertTrue(is_hallucination("これは" * 8, 2))
        self.assertFalse(is_hallucination("素晴らしいシュートでした。", 2))

    def test_partial_final_cycle_still_counts(self):
        """A chunk cut mid-hallucination ends in half a cycle (#30 feeds #31)."""
        self.assertTrue(is_hallucination("Under yourases. " * 4 + "Under your"))

    def test_boilerplate_from_whispers_training_data(self):
        """Not repetitive, not a prompt echo — nothing else catches these."""
        for text in ("And that's it for the! We'll see you next time in space!",
                     "Thanks for watching.",
                     "Thank you for watching on ewilbeat.",
                     "Subtitles by the Amara.org community",
                     "ご視聴ありがとうございました。"):
            with self.subTest(text=text):
                self.assertTrue(is_hallucination(text))

    def test_boilerplate_phrases_do_not_match_mid_match_speech(self):
        """A blocklist entry is matched anywhere in the line, so it must be specific.

        "see you in the next" would take a whole good subtitle with it; only
        the video-specific form is boilerplate.
        """
        for text in ("And we'll see you in the next few minutes after the break.",
                     "We'll see you in the next round of the cup.",
                     "Subscribe to the idea that Arsenal can win this."):
            with self.subTest(text=text):
                self.assertFalse(is_hallucination(text))

    def test_normal_commentary(self):
        self.assertFalse(is_hallucination("Salah cuts inside and shoots!"))
        self.assertFalse(is_hallucination("far far away"))

    def test_real_commentary_is_not_cyclic(self):
        """Replayed from transcriber.log: these are the shapes closest to a cycle.

        Short repetition is ordinary in commentary ("Goal! Goal! Goal!"), which
        is why the character check needs 16+ characters and 4+ cycles before it
        judges anything. Across 4854 accepted lines of a real session the two
        new checks flag 12, all of them genuine hallucinations.
        """
        for text in ("Goal! Goal! Goal!",
                     "Come on, come on!",
                     "That's a yellow card for Rice.",
                     "Saka, Saka, what a ball from Saka!",
                     "Ole, ole, ole!",
                     "It is end to end here at the Emirates.",
                     "Darwin Núñez, Luis Díaz and Mohamed Salah up front."):
            with self.subTest(text=text):
                self.assertFalse(is_hallucination(text))


PROMPT_EN = (
    "Football commentary. Terms: offside, onside, through ball, hat-trick, free kick, "
    "penalty, corner kick, goalkeeper, midfielder, striker, VAR, clean sheet, "
    "counter-attack, stoppage time, own goal, Premier League. "
    "Players: David Raya, Ben White, Declan Rice, Bukayo Saka, Kai Havertz."
)
PROMPT_ACCENTS = (
    "Football commentary. Terms: offside, free kick, penalty. "
    "Players: Darwin Núñez, Luis Díaz, Ibrahima Konaté, Mohamed Salah."
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

    def test_accented_names_are_not_split_into_extra_tokens(self):
        """Stripping diacritics inflates the word count and fakes a long run.

        "Darwin Núñez, Luis Díaz" is two names, but an ASCII-only normalisation
        turns it into six tokens ("darwin n ez luis d az") — over the threshold,
        a prompt substring, and dropped. Squad lists are full of these.
        """
        for text in ("Darwin Núñez, Luis Díaz.", "Núñez, Díaz, Konaté!",
                     "Ibrahima Konaté, Mohamed Salah."):
            with self.subTest(text=text):
                self.assertFalse(looks_like_prompt_echo(text, PROMPT_ACCENTS))

    def test_a_real_run_of_accented_names_is_still_dropped(self):
        self.assertTrue(looks_like_prompt_echo(
            "Players: Darwin Núñez, Luis Díaz, Ibrahima Konaté, Mohamed Salah.", PROMPT_ACCENTS))

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
