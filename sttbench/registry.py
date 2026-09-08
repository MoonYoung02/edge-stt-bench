"""YAML-backed model registry and adapter factory."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from sttbench.adapters.base import ModelSpec, STTAdapter


class ModelRegistry:
    def __init__(self, project_root: Path, config_path: Path | None = None):
        self.project_root = project_root
        self.config_path = config_path or project_root / "config" / "models.yaml"
        payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        configured = payload.get("models", {})
        self._models = {
            model_id: ModelSpec(
                id=model_id,
                adapter=values["adapter"],
                checkpoint=str(values["checkpoint"]),
                device=str(values.get("device", "auto")),
                options=dict(values.get("options", {})),
            )
            for model_id, values in configured.items()
        }

    def list(self) -> list[ModelSpec]:
        return list(self._models.values())

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError as exc:
            available = ", ".join(self._models)
            raise ValueError(
                f"알 수 없는 모델입니다: {model_id} (가능: {available})"
            ) from exc

    def create_adapter(self, model_id: str, *, device: str | None = None) -> STTAdapter:
        spec = self.get(model_id)
        if device is not None:
            spec = replace(spec, device=device)
        if spec.adapter == "whisper_python":
            from sttbench.adapters.whisper_python import WhisperPythonAdapter

            return WhisperPythonAdapter(spec, self.project_root)
        if spec.adapter == "whisper_cpp":
            from sttbench.adapters.whisper_cpp import WhisperCppAdapter

            return WhisperCppAdapter(spec, self.project_root)
        raise ValueError(f"등록되지 않은 어댑터입니다: {spec.adapter}")
