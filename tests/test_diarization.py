import unittest

from sttbench.diarization import SpeakerTurn, align_transcript, overlap_regions
from sttbench.schema import Segment, Transcript, Word


class DiarizationTest(unittest.TestCase):
    def test_words_are_grouped_by_assigned_speaker(self):
        transcript = Transcript(
            text="안녕 반가워요",
            language="ko",
            segments=[
                Segment(
                    id=0,
                    start=0.0,
                    end=2.0,
                    text="안녕 반가워요",
                    words=[
                        Word("안녕", 0.1, 0.8),
                        Word("반가워요", 1.2, 1.9),
                    ],
                )
            ],
        )
        turns = [SpeakerTurn(0.0, 1.0, "SPEAKER_00"), SpeakerTurn(1.0, 2.0, "SPEAKER_01")]
        utterances = align_transcript(transcript, turns)
        self.assertEqual([item.speaker for item in utterances], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual(utterances[1].text, "반가워요")

    def test_overlap_regions_require_distinct_speakers(self):
        turns = [
            SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
            SpeakerTurn(1.5, 3.0, "SPEAKER_01"),
        ]
        self.assertEqual(
            overlap_regions(turns),
            [{"start": 1.5, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]}],
        )


if __name__ == "__main__":
    unittest.main()
