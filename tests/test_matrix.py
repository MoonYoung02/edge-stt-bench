import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sttbench.adapters.base import ModelSpec
from sttbench.matrix import evaluate_matrix


class FakeRegistry:
    def __init__(self, project_root: Path):
        self.specs = {
            "tiny": ModelSpec("tiny", "fake", "tiny", "auto"),
            "base": ModelSpec("base", "fake", "base", "auto"),
        }

    def list(self) -> list[ModelSpec]:
        return list(self.specs.values())

    def get(self, model_id: str) -> ModelSpec:
        return self.specs[model_id]


class MatrixTest(unittest.TestCase):
    def test_every_model_runs_on_cpu_then_mps_and_failures_do_not_stop_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_dir = root / "data" / "kcsc" / "WAV"
            txt_dir = root / "data" / "kcsc" / "TXT"
            wav_dir.mkdir(parents=True)
            txt_dir.mkdir(parents=True)
            (wav_dir / "sample.wav").touch()
            (txt_dir / "sample.txt").touch()
            calls: list[tuple[str, str]] = []

            def fake_evaluate(project_root, model_id, *, device, language, limit):
                calls.append((model_id, device))
                if model_id == "base" and device == "mps":
                    raise RuntimeError("MPS unavailable")
                result_dir = project_root / "runs" / f"result-{model_id}-{device}"
                result_dir.mkdir(parents=True)
                (result_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "status": "completed",
                            "actual_devices": [device],
                            "completed_samples": 1,
                            "failed_samples": 0,
                            "cer": {"micro": 0.1},
                            "wer": {"micro": 0.2},
                            "rtf": 0.3,
                        }
                    ),
                    encoding="utf-8",
                )
                return result_dir

            with (
                patch("sttbench.matrix.ModelRegistry", FakeRegistry),
                patch("sttbench.matrix.evaluate_kcsc", side_effect=fake_evaluate),
                patch("sttbench.matrix.release_model_memory"),
            ):
                matrix_dir = evaluate_matrix(
                    root, devices=("cpu", "mps"), limit=1
                )

            self.assertEqual(
                calls,
                [("tiny", "cpu"), ("tiny", "mps"), ("base", "cpu"), ("base", "mps")],
            )
            summary = json.loads(
                (matrix_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["total_jobs"], 4)
            self.assertEqual(summary["completed_jobs"], 3)
            self.assertEqual(summary["failed_jobs"], 1)
            self.assertEqual(summary["status"], "completed_with_errors")
            self.assertTrue((matrix_dir / "summary.md").is_file())


if __name__ == "__main__":
    unittest.main()
