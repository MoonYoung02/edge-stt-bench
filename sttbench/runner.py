"""One-file inspection orchestration independent of a specific STT engine."""

from __future__ import annotations

from datetime import datetime
import platform
from pathlib import Path
import re
import sys
import time
import unicodedata

from sttbench.adapters.base import TranscriptionRequest
from sttbench.artifacts import save_artifacts, write_json
from sttbench.datasets.kcsc import find_reference, parse_reference
from sttbench.progress import format_elapsed, show_runtime_estimate
from sttbench.registry import ModelRegistry

SAMPLE_RATE = 16_000
AUDIO_EXTENSIONS = {
    ".wav",
    ".m4a",
    ".mp3",
    ".flac",
    ".ogg",
    ".opus",
    ".aac",
    ".mp4",
    ".webm",
    ".mpeg",
    ".mpga",
}


def inspect_audio(
    project_root: Path,
    audio: Path,
    model_id: str,
    language: str = "auto",
    *,
    device: str | None = None,
    diarize: bool = False,
    num_speakers: int | None = None,
    diarization_device: str = "auto",
) -> Path:
    overall_started = time.perf_counter()
    started_at = datetime.now().astimezone()
    audio_path = resolve_audio(audio)
    registry = ModelRegistry(project_root)
    spec = registry.get(model_id)
    adapter = registry.create_adapter(model_id, device=device)
    effective_spec = adapter.spec
    adapter.prepare()
    status = adapter.check()
    if not status.ready:
        raise RuntimeError(f"{model_id}을 실행할 수 없습니다: {status.detail}")

    run_id = make_run_id(audio_path, model_id, started_at)
    run_dir = project_root / "runs" / run_id
    sample_dir = run_dir / "samples" / safe_name(audio_path.stem)
    raw_dir = sample_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)

    print(f"입력: {audio_path}")
    print(f"모델: {model_id}")
    print(f"어댑터: {spec.adapter}")
    print(f"장치: {effective_spec.device}")
    estimate = show_runtime_estimate(
        project_root, audio_path, model_id, diarize=diarize
    )

    result = adapter.transcribe(
        TranscriptionRequest(audio_path=audio_path, work_dir=raw_dir, language=language)
    )
    artifacts_started = time.perf_counter()
    reference_path = find_reference(audio_path, project_root)
    references = parse_reference(reference_path) if reference_path else None
    comparison, warnings = save_artifacts(sample_dir, audio_path, result, references)
    artifacts_seconds = time.perf_counter() - artifacts_started
    diarization_summary = None
    if diarize:
        from sttbench.diarization import run_diarization, save_diarization_artifacts

        diarization_result = run_diarization(
            project_root,
            audio_path,
            raw_dir,
            num_speakers=num_speakers,
            device=diarization_device,
        )
        diarization_summary = save_diarization_artifacts(
            sample_dir, audio_path, result.transcript, diarization_result
        )
    total_seconds = time.perf_counter() - overall_started
    audio_seconds = len(result.audio) / SAMPLE_RATE
    timings = {
        **result.timings,
        "artifacts_seconds": artifacts_seconds,
        "total_seconds": total_seconds,
    }
    if diarization_summary:
        timings["diarization_seconds"] = diarization_summary["seconds"]
    comparison_summary = None
    if comparison:
        comparison_summary = {
            key: comparison[key]
            for key in (
                "cer",
                "wer",
                "character_errors",
                "reference_characters",
                "word_errors",
                "reference_words",
                "reference_segments",
            )
        }
    summary = {
        "run_id": run_id,
        "status": "completed",
        "command": "inspect",
        "input": str(audio_path),
        "reference": str(reference_path) if reference_path else None,
        "model": model_id,
        "adapter": spec.adapter,
        "checkpoint": spec.checkpoint,
        "engine": result.engine,
        "device": result.device,
        "language": result.transcript.language,
        "requested_language": language,
        "audio_seconds": audio_seconds,
        "rtf": result.timings.get("transcribe_seconds", 0.0) / max(audio_seconds, 1e-9),
        "runtime_estimate": estimate,
        "timings": timings,
        "total_seconds": total_seconds,
        "segments": len(result.transcript.segments),
        "words": sum(len(segment.words) for segment in result.transcript.segments),
        "tokens": sum(len(segment.tokens) for segment in result.transcript.segments),
        "comparison": comparison_summary,
        "diarization": diarization_summary,
        "warnings": warnings,
    }
    write_json(run_dir / "summary.json", summary)
    write_json(
        run_dir / "run.json",
        {
            **summary,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "platform": platform.platform(),
            "python": sys.version,
            "model_config": {
                "id": spec.id,
                "adapter": spec.adapter,
                "checkpoint": spec.checkpoint,
                "device": effective_spec.device,
                "options": effective_spec.options,
            },
            "engine_metadata": result.metadata,
        },
    )

    print("\n최종 STT 결과")
    print(result.transcript.text)
    print("\n실행 시간")
    for label, key in (
        ("모델 로드", "model_load_seconds"),
        ("전처리", "preprocess_seconds"),
        ("STT", "transcribe_seconds"),
        ("화자 분리", "diarization_seconds"),
        ("산출물 저장", "artifacts_seconds"),
    ):
        if key in timings:
            print(f"{label}: {format_elapsed(timings[key])}")
    print(f"전체: {format_elapsed(total_seconds)} ({total_seconds:.2f}초)")
    print(f"RTF: {summary['rtf']:.3f} (1보다 작으면 실시간보다 빠름)")
    print(f"\n모든 산출물: {run_dir}")
    print(f"공통 전사 결과: {sample_dir / 'transcript.json'}")
    print(f"구간별 전사: {sample_dir / 'transcript_labeled.txt'}")
    if diarization_summary:
        print(f"화자별 전사: {sample_dir / 'speaker_transcript.txt'}")
        print(
            f"감지 화자: {diarization_summary['speaker_count']}명 / "
            f"겹침 구간: {diarization_summary['overlap_regions']}개"
        )
    if reference_path:
        print(f"정답 화자/텍스트: {sample_dir / 'reference_labeled.txt'}")
    return run_dir


def resolve_audio(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"오디오 파일이 없습니다: {resolved}")
    if resolved.suffix.lower() not in AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise ValueError(
            f"지원하지 않는 오디오 형식입니다: {resolved.suffix} (가능: {supported})"
        )
    return resolved


def safe_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", normalized).strip("-._")
    return cleaned or "audio"


def make_run_id(audio_path: Path, model_id: str, started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{timestamp}__{safe_name(audio_path.stem)}__{safe_name(model_id)}"
