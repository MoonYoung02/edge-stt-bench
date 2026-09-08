import unittest
from pathlib import Path

from sttbench.adapters.base import ModelSpec
from sttbench.adapters.whisper_python import WhisperPythonAdapter


class FakeWhisper:
    def __init__(self):
        self.calls = 0

    def load_model(self, checkpoint: str, *, device: str):
        self.calls += 1
        return {"checkpoint": checkpoint, "device": device}


class WhisperPythonAdapterTest(unittest.TestCase):
    def test_model_is_loaded_once_and_reused(self):
        spec = ModelSpec("base", "whisper_python", "base", "cpu")
        adapter = WhisperPythonAdapter(spec, Path("."))
        whisper = FakeWhisper()

        first, first_seconds = adapter._load_model(whisper, "cpu")
        second, second_seconds = adapter._load_model(whisper, "cpu")

        self.assertIs(first, second)
        self.assertEqual(whisper.calls, 1)
        self.assertGreaterEqual(first_seconds, 0.0)
        self.assertEqual(second_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
