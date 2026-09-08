import unittest

from sttbench.metrics.text import compare, normalize_text


class TextMetricsTest(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_text("안녕, 하세요!"), "안녕 하세요")

    def test_identical_text_has_zero_errors(self):
        result = compare("방 탈출 카페", "방 탈출 카페")
        self.assertEqual(result["cer"], 0)
        self.assertEqual(result["wer"], 0)

    def test_character_error(self):
        result = compare("가나다", "가마")
        self.assertGreater(result["cer"], 0)


if __name__ == "__main__":
    unittest.main()

