import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from sttbench.adapters.base import (
    AdapterResult,
    AdapterStatus,
    ModelSpec,
    TranscriptionRequest,
)
from sttbench.evaluator import evaluate_kcsc
from sttbench.schema import Segment, Transcript, Word


class FakeAdapter:
    def __init__(self):
        self.spec = ModelSpec(
            id="fake",
            adapter="fake",
            checkpoint="fake-checkpoint",
            device="cpu",
        )
        self.calls: list[str] = []

    def check(self) -> AdapterStatus:
        return AdapterStatus(True, "ready")

    def prepare(self) -> None:
        return None

    def transcribe(self, request: TranscriptionRequest) -> AdapterResult:
        self.calls.append(request.audio_path.stem)
        transcript = Transcript(
            text="안녕하세요",
            language="ko",
            segments=[
                Segment(
                    id=0,
                    start=0.0,
                    end=1.0,
                    text="안녕하세요",
                    words=[Word("안녕하세요", 0.0, 1.0, 0.9)],
                )
            ],
        )
        return AdapterResult(
            transcript=transcript,
            engine="fake-engine",
            device="cpu",
            audio=np.zeros(16_000, dtype=np.float32),
            mel=np.zeros((80, 10), dtype=np.float32),
            raw_result={"text": "안녕하세요"},
            timings={
                "model_load_seconds": 0.2 if len(self.calls) == 1 else 0.0,
                "transcribe_seconds": 0.1,
            },
        )


class FakeRegistry:
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter

    def get(self, model_id: str) -> ModelSpec:
        return self.adapter.spec

    def create_adapter(
        self, model_id: str, *, device: str | None = None
    ) -> FakeAdapter:
        return self.adapter


class EvaluatorTest(unittest.TestCase):
    def test_kcsc_batch_writes_per_sample_and_summary_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_dir = root / "data" / "kcsc" / "WAV"
            txt_dir = root / "data" / "kcsc" / "TXT"
            wav_dir.mkdir(parents=True)
            txt_dir.mkdir(parents=True)
            (wav_dir / "sample-a.wav").touch()
            (wav_dir / "sample-b.wav").touch()
            (txt_dir / "sample-a.txt").write_text(
                "[0.000,1.000] G0001 female 안녕하세요\n",
                encoding="utf-8",
            )
            adapter = FakeAdapter()
            registry = FakeRegistry(adapter)

            with patch("sttbench.evaluator.ModelRegistry", return_value=registry):
                run_dir = evaluate_kcsc(root, "fake", device="cpu")

            sample_a = run_dir / "samples" / "sample-a"
            sample_b = run_dir / "samples" / "sample-b"
            self.assertTrue((sample_a / "prediction.json").is_file())
            self.assertTrue((sample_a / "prediction.md").is_file())
            self.assertTrue((sample_a / "reference.txt").is_file())
            self.assertTrue((sample_a / "comparison.json").is_file())
            self.assertTrue((sample_b / "prediction.json").is_file())
            self.assertTrue((sample_b / "comparison.json").is_file())
            self.assertIn(
                "```text", (sample_a / "prediction.md").read_text(encoding="utf-8")
            )
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["completed_samples"], 1)
            self.assertEqual(summary["failed_samples"], 1)
            self.assertEqual(summary["cer"]["micro"], 0.0)
            self.assertEqual(adapter.calls, ["sample-a"])

            (txt_dir / "sample-b.txt").write_text(
                "[0.000,1.000] G0002 male 안녕하세요\n",
                encoding="utf-8",
            )
            with patch("sttbench.evaluator.ModelRegistry", return_value=registry):
                resumed_dir = evaluate_kcsc(root, "fake", device="cpu", resume=True)

            self.assertEqual(resumed_dir, run_dir)
            resumed_summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(resumed_summary["completed_samples"], 2)
            self.assertEqual(resumed_summary["failed_samples"], 0)
            self.assertEqual(adapter.calls, ["sample-a", "sample-b"])


if __name__ == "__main__":
    unittest.main()
