import unittest
from pathlib import Path

from sttbench.registry import ModelRegistry


ROOT = Path(__file__).resolve().parents[1]


class RegistryTest(unittest.TestCase):
    def test_expected_models_exist(self):
        registry = ModelRegistry(ROOT)
        self.assertEqual(registry.get("large-v3-turbo").adapter, "whisper_python")
        self.assertEqual(registry.get("whisper-cpp-base-q5_1").adapter, "whisper_cpp")

    def test_unknown_model_is_clear_error(self):
        with self.assertRaisesRegex(ValueError, "알 수 없는 모델"):
            ModelRegistry(ROOT).get("missing")

    def test_device_can_be_overridden_when_adapter_is_created(self):
        adapter = ModelRegistry(ROOT).create_adapter("base", device="cpu")
        self.assertEqual(adapter.spec.device, "cpu")


if __name__ == "__main__":
    unittest.main()
