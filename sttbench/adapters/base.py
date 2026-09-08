"""Adapter contract for integrating an STT engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sttbench.schema import Transcript


@dataclass(frozen=True)
class ModelSpec:
    id: str
    adapter: str
    checkpoint: str
    device: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterStatus:
    ready: bool
    detail: str


@dataclass(frozen=True)
class TranscriptionRequest:
    audio_path: Path
    work_dir: Path
    language: str = "auto"


@dataclass
class AdapterResult:
    transcript: Transcript
    engine: str
    device: str
    audio: np.ndarray
    mel: np.ndarray
    raw_result: Any
    timings: dict[str, float] = field(default_factory=dict)
    language_probabilities: dict[str, float] = field(default_factory=dict)
    log: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class STTAdapter(ABC):
    def __init__(self, spec: ModelSpec, project_root: Path):
        self.spec = spec
        self.project_root = project_root

    def prepare(self) -> None:
        """Download or otherwise prepare local model files when necessary."""

    @abstractmethod
    def check(self) -> AdapterStatus:
        """Return whether this model can run on the current machine."""

    @abstractmethod
    def transcribe(self, request: TranscriptionRequest) -> AdapterResult:
        """Transcribe one audio file and return canonical plus raw results."""
