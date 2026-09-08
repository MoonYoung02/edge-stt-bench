import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sttbench.datasets.kcsc import discover_samples, download_dataset, parse_reference


class KcscTest(unittest.TestCase):
    def test_reference_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text(
                "[10.730,15.910] G0101 male 방 탈출 카페를 좋아해요.\n",
                encoding="utf-8",
            )
            segment = parse_reference(path)[0]
        self.assertEqual(segment.speaker, "G0101")
        self.assertEqual(segment.gender, "male")
        self.assertEqual(segment.start, 10.73)

    def test_samples_are_discovered_in_stable_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_dir = root / "WAV"
            txt_dir = root / "TXT"
            wav_dir.mkdir()
            txt_dir.mkdir()
            (wav_dir / "b.wav").touch()
            (wav_dir / "a.wav").touch()
            (txt_dir / "a.txt").touch()
            samples = discover_samples(root, limit=1)

        self.assertEqual([sample.id for sample in samples], ["a"])
        self.assertEqual(samples[0].reference.name, "a.txt")

    def test_download_uses_expected_local_layout(self):
        fake_hub = types.ModuleType("huggingface_hub")

        def snapshot_download(**kwargs):
            destination = Path(kwargs["local_dir"])
            (destination / "WAV").mkdir(parents=True)
            (destination / "TXT").mkdir(parents=True)
            (destination / "WAV" / "sample.wav").touch()
            (destination / "TXT" / "sample.txt").touch()

        fake_hub.snapshot_download = snapshot_download
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(sys.modules, {"huggingface_hub": fake_hub}):
                dataset_root = download_dataset(root)

            self.assertTrue((dataset_root / "WAV" / "sample.wav").is_file())
            self.assertTrue((dataset_root / "TXT" / "sample.txt").is_file())


if __name__ == "__main__":
    unittest.main()
