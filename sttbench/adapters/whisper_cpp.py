"""Adapter for whisper.cpp quantized models."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

from sttbench.adapters.base import (
    AdapterResult,
    AdapterStatus,
    STTAdapter,
    TranscriptionRequest,
)
from sttbench.progress import run_process_with_progress
from sttbench.schema import Segment, Token, Transcript, Word

NATIVE_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg"}

_QUANTIZATION_PATTERN = re.compile(r"(q\d+_(?:\d+|k))", re.IGNORECASE)


def _infer_quantization(model_path: Path) -> str:
    """Derive the GGML quantization label (e.g. Q5_1, Q8_0) from the checkpoint filename."""
    match = _QUANTIZATION_PATTERN.search(model_path.stem)
    return match.group(1).upper() if match else "none"


def _resolve_device(system_info: str, command: list[str]) -> str:
    """Report the device actually used for compute, not just what the binary supports.

    ``systeminfo`` only describes which backends whisper-cli was *compiled* with
    (e.g. "MTL : EMBED_LIBRARY = 1" appears even when Metal is never touched at
    runtime), so it must not be used on its own to decide the device. ``--no-gpu``
    is what actually forces CPU-only execution, so that takes priority.
    """
    if "--no-gpu" in command:
        return "cpu"
    return "mps" if "MTL" in system_info else "cpu"


class WhisperCppAdapter(STTAdapter):
    @property
    def model_path(self) -> Path:
        path = Path(self.spec.checkpoint)
        return path if path.is_absolute() else self.project_root / path

    def prepare(self) -> None:
        if self.model_path.is_file():
            return
        if shutil.which("whisper-cli") is None:
            raise RuntimeError(
                "whisper.cpp 모델을 실행하려면 먼저 whisper-cli를 설치해야 합니다."
            )
        repo_id = self.spec.options.get("model_repo")
        filename = self.spec.options.get("model_file")
        if not repo_id or not filename:
            raise RuntimeError(
                f"모델 파일이 없고 자동 다운로드 정보도 없습니다: {self.model_path}"
            )
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise RuntimeError(
                "whisper.cpp 모델 다운로드에는 huggingface-hub 패키지가 필요합니다."
            ) from exc
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"whisper.cpp 모델을 내려받는 중: {repo_id}/{filename}")
        downloaded = Path(
            hf_hub_download(
                repo_id=str(repo_id),
                filename=str(filename),
                local_dir=self.model_path.parent,
            )
        )
        if downloaded.resolve() != self.model_path.resolve():
            shutil.copyfile(downloaded, self.model_path)
        print(f"모델 준비 완료: {self.model_path}")

    def check(self) -> AdapterStatus:
        if self.spec.device.lower() not in {"auto", "cpu", "mps", "metal"}:
            return AdapterStatus(
                False, f"whisper_cpp가 지원하지 않는 장치입니다: {self.spec.device}"
            )
        executable = shutil.which("whisper-cli")
        if executable is None:
            return AdapterStatus(False, "whisper-cli 없음")
        if not self.model_path.is_file():
            return AdapterStatus(False, f"모델 파일 없음: {self.model_path}")
        requested = self.spec.device.lower()
        device = "CPU" if requested == "cpu" else "Metal 자동 감지"
        return AdapterStatus(True, f"{device} / 모델 준비됨 ({self.model_path.name})")

    def transcribe(self, request: TranscriptionRequest) -> AdapterResult:
        import whisper

        executable = shutil.which("whisper-cli")
        if executable is None:
            raise RuntimeError(
                "whisper-cli가 없습니다. 'brew install whisper-cpp'를 실행하세요."
            )
        request.work_dir.mkdir(parents=True, exist_ok=True)

        print("Whisper 입력을 계산하는 중...")
        started = time.perf_counter()
        audio = whisper.load_audio(str(request.audio_path))
        mel = whisper.log_mel_spectrogram(audio, n_mels=80).cpu().numpy()
        engine_input = request.audio_path
        converted = False
        if request.audio_path.suffix.lower() not in NATIVE_EXTENSIONS:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise RuntimeError("이 오디오 형식을 변환하려면 ffmpeg가 필요합니다.")
            engine_input = request.work_dir / "converted_input_16k.wav"
            conversion = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(request.audio_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(engine_input),
                ],
                capture_output=True,
                text=True,
            )
            if conversion.returncode:
                raise RuntimeError(f"오디오 변환 실패: {conversion.stderr.strip()}")
            converted = True
            print(f"whisper.cpp용 WAV 자동 변환: {engine_input.name}")
        preprocess_seconds = time.perf_counter() - started

        prefix = request.work_dir / "whisper_cpp"
        command = [
            executable,
            "-m",
            str(self.model_path),
            "-f",
            str(engine_input),
            "-l",
            request.language,
            "-mc",
            "0",
            "-ojf",
            "-otxt",
            "-osrt",
            "-ovtt",
            "-ocsv",
            "-pp",
            "-of",
            str(prefix),
            "--no-prints",
        ]
        if self.spec.device.lower() == "cpu":
            command.append("--no-gpu")
        print("STT를 실행하는 중... (진행률과 ETA)")
        returncode, output, transcribe_seconds = run_process_with_progress(command)
        if returncode:
            raise RuntimeError(f"whisper-cli 실행 실패:\n{output[-2000:]}")

        for path in request.work_dir.glob("whisper_cpp.*"):
            path.write_text(
                path.read_bytes().decode("utf-8", errors="replace"), encoding="utf-8"
            )
        raw_path = prefix.with_suffix(".json")
        raw_result = json.loads(raw_path.read_text(encoding="utf-8"))
        transcript = _canonical_transcript(raw_result)
        version = _version(executable)
        system_info = raw_result.get("systeminfo", "")
        return AdapterResult(
            transcript=transcript,
            engine="whisper.cpp",
            device=_resolve_device(system_info, command),
            audio=np.asarray(audio, dtype=np.float32),
            mel=np.asarray(mel),
            raw_result=raw_result,
            timings={
                "preprocess_seconds": preprocess_seconds,
                "transcribe_seconds": transcribe_seconds,
            },
            log="COMMAND\n" + " ".join(command) + "\n\nOUTPUT\n" + output,
            metadata={
                "checkpoint": str(self.model_path),
                "model_bytes": self.model_path.stat().st_size,
                "engine_version": version,
                "engine_input": str(engine_input),
                "input_converted_to_wav": converted,
                "quantization": _infer_quantization(self.model_path),
                "decoding": {"max_context": 0, "word_timestamps": True},
            },
        )


def _canonical_transcript(raw_result: dict) -> Transcript:
    segments: list[Segment] = []
    texts: list[str] = []
    for segment_id, item in enumerate(raw_result.get("transcription", [])):
        offsets = item.get("offsets", {})
        text = item.get("text", "").strip()
        if text:
            texts.append(text)
        tokens: list[Token] = []
        words: list[Word] = []
        active: dict | None = None
        for token in item.get("tokens", []):
            token_offsets = token.get("offsets", {})
            start = float(token_offsets.get("from", 0)) / 1000
            end = float(token_offsets.get("to", 0)) / 1000
            piece = token.get("text", "")
            probability = _float_or_none(token.get("p"))
            tokens.append(
                Token(
                    text=piece,
                    id=token.get("id"),
                    start=start,
                    end=end,
                    confidence=probability,
                )
            )
            if piece.startswith("[") and piece.endswith("]"):
                continue
            if piece.startswith(" ") and active:
                words.append(_finish_word(active))
                active = None
            if active is None:
                active = {
                    "text": piece.strip(),
                    "start": start,
                    "end": end,
                    "probabilities": [],
                }
            else:
                active["text"] += piece
                active["end"] = max(active["end"], end)
            if probability is not None:
                active["probabilities"].append(probability)
        if active:
            words.append(_finish_word(active))
        segments.append(
            Segment(
                id=segment_id,
                start=float(offsets.get("from", 0)) / 1000,
                end=float(offsets.get("to", 0)) / 1000,
                text=text,
                words=words,
                tokens=tokens,
            )
        )
    return Transcript(
        text=" ".join(texts),
        language=raw_result.get("result", {}).get("language"),
        segments=segments,
    )


def _finish_word(raw: dict) -> Word:
    probabilities = raw["probabilities"]
    return Word(
        text=raw["text"],
        start=raw["start"],
        end=raw["end"],
        confidence=sum(probabilities) / len(probabilities) if probabilities else None,
    )


def _float_or_none(value) -> float | None:
    return None if value is None else float(value)


def _version(executable: str) -> str:
    process = subprocess.run([executable, "--version"], capture_output=True, text=True)
    match = re.search(r"whisper\.cpp version:\s*(\S+)", process.stdout + process.stderr)
    return match.group(1) if match else "unknown"
