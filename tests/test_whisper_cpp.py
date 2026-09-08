import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from sttbench.adapters.base import ModelSpec
from sttbench.adapters.whisper_cpp import (
    WhisperCppAdapter,
    _infer_quantization,
    _resolve_device,
)

# whisper-cli always reports which backends it was *compiled* with, regardless
# of whether they were actually used for this run.
METAL_CAPABLE_SYSTEMINFO = (
    "WHISPER : COREML = 0 | OPENVINO = 0 | MTL : EMBED_LIBRARY = 1 | "
    "CPU : NEON = 1 | ARM_FMA = 1 | ACCELERATE = 1 |"
)
CPU_ONLY_SYSTEMINFO = "WHISPER : COREML = 0 | OPENVINO = 0 | CPU : NEON = 1 |"


class QuantizationInferenceTest(unittest.TestCase):
    def test_recognizes_each_catalog_quantization(self):
        cases = {
            "ggml-tiny-q5_1.bin": "Q5_1",
            "ggml-tiny-q8_0.bin": "Q8_0",
            "ggml-base-q5_1.bin": "Q5_1",
            "ggml-base-q8_0.bin": "Q8_0",
            "ggml-small-q5_1.bin": "Q5_1",
            "ggml-small-q8_0.bin": "Q8_0",
            "ggml-medium-q5_0.bin": "Q5_0",
            "ggml-medium-q8_0.bin": "Q8_0",
            "ggml-large-v3-turbo-q5_0.bin": "Q5_0",
            "ggml-large-v3-turbo-q8_0.bin": "Q8_0",
            "ggml-large-v3-q5_0.bin": "Q5_0",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(_infer_quantization(Path(filename)), expected)

    def test_unquantized_checkpoint_reports_none(self):
        self.assertEqual(_infer_quantization(Path("ggml-base.bin")), "none")


class DeviceResolutionTest(unittest.TestCase):
    def test_no_gpu_flag_always_reports_cpu_even_if_metal_capable(self):
        # Reproduces the bug where a --device cpu run (--no-gpu passed) was
        # misreported as "mps" just because the binary happens to be Metal-capable.
        command = ["whisper-cli", "-m", "model.bin", "--no-gpu"]
        self.assertEqual(_resolve_device(METAL_CAPABLE_SYSTEMINFO, command), "cpu")

    def test_metal_capable_without_no_gpu_reports_mps(self):
        command = ["whisper-cli", "-m", "model.bin"]
        self.assertEqual(_resolve_device(METAL_CAPABLE_SYSTEMINFO, command), "mps")

    def test_cpu_only_binary_without_no_gpu_reports_cpu(self):
        command = ["whisper-cli", "-m", "model.bin"]
        self.assertEqual(_resolve_device(CPU_ONLY_SYSTEMINFO, command), "cpu")


class WhisperCppAdapterTest(unittest.TestCase):
    def test_missing_model_is_downloaded_once(self):
        calls: list[tuple[str, str]] = []
        fake_hub = types.ModuleType("huggingface_hub")

        def hf_hub_download(*, repo_id: str, filename: str, local_dir: Path):
            calls.append((repo_id, filename))
            path = Path(local_dir) / filename
            path.write_bytes(b"model")
            return str(path)

        fake_hub.hf_hub_download = hf_hub_download
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = ModelSpec(
                "whisper-base-q5_1",
                "whisper_cpp",
                "models/ggml-base-q5_1.bin",
                "cpu",
                {
                    "model_repo": "ggerganov/whisper.cpp",
                    "model_file": "ggml-base-q5_1.bin",
                },
            )
            adapter = WhisperCppAdapter(spec, root)
            with (
                patch.dict(sys.modules, {"huggingface_hub": fake_hub}),
                patch(
                    "sttbench.adapters.whisper_cpp.shutil.which",
                    return_value="whisper-cli",
                ),
            ):
                adapter.prepare()
                adapter.prepare()

            self.assertTrue((root / "models" / "ggml-base-q5_1.bin").is_file())
            self.assertEqual(calls, [("ggerganov/whisper.cpp", "ggml-base-q5_1.bin")])


if __name__ == "__main__":
    unittest.main()
