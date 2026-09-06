import unittest

from football_transcriber.text_filters import is_hallucination


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


if __name__ == "__main__":
    unittest.main()
