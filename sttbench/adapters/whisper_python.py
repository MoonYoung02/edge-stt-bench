"""Adapter for the openai-whisper Python package on Apple MPS."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np

from sttbench.adapters.base import (
    AdapterResult,
    AdapterStatus,
    ModelSpec,
    STTAdapter,
    TranscriptionRequest,
)
from sttbench.schema import Segment, Token, Transcript, Word


class WhisperPythonAdapter(STTAdapter):
    def __init__(self, spec: ModelSpec, project_root: Path):
        super().__init__(spec, project_root)
        self._model = None

    def _resolved_device(self, torch) -> str:
        requested = self.spec.device.lower()
        if requested == "auto":
            return (
                "mps"
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                else "cpu"
            )
        if requested not in {"cpu", "mps"}:
            raise ValueError(
                f"whisper_python이 지원하지 않는 장치입니다: {self.spec.device}"
            )
        return requested

    def _load_model(self, whisper, device: str):
        model_seconds = 0.0
        if self._model is None:
            print("모델을 불러오는 중...")
            started = time.perf_counter()
            self._model = whisper.load_model(self.spec.checkpoint, device=device)
            model_seconds = time.perf_counter() - started
        return self._model, model_seconds

    def check(self) -> AdapterStatus:
        try:
            import torch
            import whisper  # noqa: F401
        except ImportError as exc:
            return AdapterStatus(False, f"Python 패키지 없음: {exc.name}")
        try:
            device = self._resolved_device(torch)
        except ValueError as exc:
            return AdapterStatus(False, str(exc))
        mps_ready = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        if device == "mps" and not mps_ready:
            return AdapterStatus(False, "MPS 사용 불가")
        cached = Path.home() / ".cache" / "whisper" / f"{self.spec.checkpoint}.pt"
        cache_status = "모델 캐시됨" if cached.is_file() else "첫 실행 때 모델 다운로드"
        detail = f"{device.upper()} 사용 가능 / {cache_status}"
        return AdapterStatus(True, detail)

    def transcribe(self, request: TranscriptionRequest) -> AdapterResult:
        import torch
        import whisper
        import whisper.timing as whisper_timing
        from whisper.audio import N_FRAMES
        from whisper.tokenizer import get_tokenizer

        device = self._resolved_device(torch)
        model, model_seconds = self._load_model(whisper, device)

        print("Whisper 입력과 언어 확률을 계산하는 중...")
        started = time.perf_counter()
        audio = whisper.load_audio(str(request.audio_path))
        mel_tensor = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
        mel = mel_tensor.cpu().numpy()
        input_dtype = torch.float16 if device == "mps" else torch.float32
        language_input = whisper.pad_or_trim(mel_tensor, N_FRAMES).to(
            device=model.device,
            dtype=input_dtype,
        )
        _, probabilities = model.detect_language(language_input)
        detected_language = max(probabilities, key=probabilities.get)
        language = detected_language if request.language == "auto" else request.language
        preprocess_seconds = time.perf_counter() - started
        print(f"감지 언어: {detected_language}")

        original_dtw = whisper_timing.dtw

        def mps_safe_dtw(tensor):
            if tensor.device.type == "mps":
                return whisper_timing.dtw_cpu(tensor.cpu().double().numpy())
            return original_dtw(tensor)

        whisper_timing.dtw = mps_safe_dtw
        print("STT를 실행하는 중... (진행률과 ETA)")
        started = time.perf_counter()
        try:
            raw_result = model.transcribe(
                audio,
                language=language,
                task="transcribe",
                fp16=device == "mps",
                temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                condition_on_previous_text=False,
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
                word_timestamps=True,
                verbose=False,
            )
        finally:
            whisper_timing.dtw = original_dtw
        transcribe_seconds = time.perf_counter() - started

        tokenizer = get_tokenizer(
            model.is_multilingual,
            language=raw_result.get("language"),
            task="transcribe",
            num_languages=model.num_languages,
        )
        segments: list[Segment] = []
        for raw_segment in raw_result.get("segments", []):
            words = [
                Word(
                    text=word.get("word", ""),
                    start=_float_or_none(word.get("start")),
                    end=_float_or_none(word.get("end")),
                    confidence=_float_or_none(word.get("probability")),
                )
                for word in raw_segment.get("words", [])
            ]
            tokens = [
                Token(id=int(token_id), text=tokenizer.decode([token_id]))
                for token_id in raw_segment.get("tokens", [])
            ]
            known = {"id", "start", "end", "text", "words", "tokens"}
            segments.append(
                Segment(
                    id=int(raw_segment.get("id", len(segments))),
                    start=float(raw_segment.get("start", 0.0)),
                    end=float(raw_segment.get("end", 0.0)),
                    text=raw_segment.get("text", "").strip(),
                    words=words,
                    tokens=tokens,
                    metadata={
                        key: value
                        for key, value in raw_segment.items()
                        if key not in known
                    },
                )
            )
        transcript = Transcript(
            text=raw_result.get("text", "").strip(),
            language=raw_result.get("language", detected_language),
            segments=segments,
            metadata={"detected_language": detected_language},
        )
        return AdapterResult(
            transcript=transcript,
            engine="openai-whisper",
            device=device,
            audio=np.asarray(audio, dtype=np.float32),
            mel=np.asarray(mel),
            raw_result=raw_result,
            timings={
                "model_load_seconds": model_seconds,
                "preprocess_seconds": preprocess_seconds,
                "transcribe_seconds": transcribe_seconds,
            },
            language_probabilities={
                key: float(value) for key, value in probabilities.items()
            },
            metadata={
                "fp16": device == "mps",
                "checkpoint": self.spec.checkpoint,
                "decoding": {
                    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                    "condition_on_previous_text": False,
                    "compression_ratio_threshold": 2.4,
                    "logprob_threshold": -1.0,
                    "no_speech_threshold": 0.6,
                    "word_timestamps": True,
                },
            },
        )


def _float_or_none(value) -> float | None:
    return None if value is None else float(value)
