import unittest

from sttbench.schema import Segment, Transcript, Word


class SchemaTest(unittest.TestCase):
    def test_nested_schema_serializes(self):
        transcript = Transcript(
            text="안녕하세요",
            language="ko",
            segments=[
                Segment(
                    id=0,
                    start=0.0,
                    end=1.0,
                    text="안녕하세요",
                    words=[Word(text="안녕하세요", start=0.0, end=1.0, confidence=0.9)],
                )
            ],
        )
        payload = transcript.to_dict()
        self.assertEqual(payload["language"], "ko")
        self.assertEqual(payload["segments"][0]["words"][0]["text"], "안녕하세요")


if __name__ == "__main__":
    unittest.main()

