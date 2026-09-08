"""Repeatable KCSC batch evaluation and compact benchmark artifacts."""

from __future__ import annotations

from datetime import datetime
import json
import platform
from pathlib import Path
import shutil
import statistics
import sys
import time
from typing import Any

from sttbench.adapters.base import STTAdapter, TranscriptionRequest
from sttbench.artifacts import save_tables, write_json
from sttbench.datasets.kcsc import KcscSample, discover_samples, parse_reference
from sttbench.metrics.text import compare
from sttbench.registry import ModelRegistry
from sttbench.runner import safe_name

SAMPLE_RATE = 16_000


def evaluate_kcsc(
    project_root: Path,
    model_id: str,
    *,
    device: str = "auto",
    language: str = "ko",
    limit: int | None = None,
    resume: bool = False,
) -> Path:
    dataset_root = project_root / "data" / "kcsc"
    samples = discover_samples(dataset_root, limit=limit)
    if not samples:
        raise ValueError(f"평가할 KCSC WAV 파일이 없습니다: {dataset_root / 'WAV'}")

    registry = ModelRegistry(project_root)
    configured_spec = registry.get(model_id)
    adapter = registry.create_adapter(model_id, device=device)
    adapter.prepare()
    status = adapter.check()
    if not status.ready:
        raise RuntimeError(f"{model_id}을 실행할 수 없습니다: {status.detail}")

    started_at = datetime.now().astimezone()
    if resume:
        run_dir = _find_resume_run(project_root, model_id, device, language, limit)
        run_payload = _read_json(run_dir / "run.json")
        original_started_at = str(run_payload.get("started_at", started_at.isoformat()))
    else:
        run_id = make_run_id(model_id, device, started_at)
        run_dir = project_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        original_started_at = started_at.isoformat(timespec="seconds")

    run_payload = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "status": "running",
        "command": "evaluate",
        "dataset": "kcsc",
        "dataset_root": str(dataset_root),
        "model": model_id,
        "adapter": configured_spec.adapter,
        "checkpoint": configured_spec.checkpoint,
        "requested_device": device,
        "language": language,
        "limit": limit,
        "started_at": original_started_at,
        "resumed_at": started_at.isoformat(timespec="seconds") if resume else None,
        "platform": platform.platform(),
        "python": sys.version,
    }
    write_json(run_dir / "run.json", run_payload)

    overall_started = time.perf_counter()
    records: list[dict[str, Any]] = []
    total = len(samples)
    for index, sample in enumerate(samples, start=1):
        sample_dir = run_dir / "samples" / safe_name(sample.id)
        if resume:
            existing = _existing_record(sample_dir)
            if existing is not None:
                records.append(existing)
                print(f"[{index}/{total}] {sample.id}: 완료된 결과 재사용")
                continue
        print(f"[{index}/{total}] {sample.id}: 전사 중")
        records.append(
            _evaluate_sample(adapter, sample, sample_dir, model_id, language)
        )

    total_seconds = time.perf_counter() - overall_started
    summary = build_summary(
        run_dir=run_dir,
        records=records,
        model_id=model_id,
        requested_device=device,
        language=language,
        total_seconds=total_seconds,
    )
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", summary)
    write_json(
        run_dir / "run.json",
        {
            **run_payload,
            "status": summary["status"],
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "actual_devices": summary["actual_devices"],
            "summary": str(run_dir / "summary.json"),
        },
    )

    print(
        f"\nKCSC 평가 완료: {summary['completed_samples']}/{summary['total_samples']}개 성공"
    )
    print(f"CER: {_format_rate(summary['cer']['micro'])}")
    print(f"WER: {_format_rate(summary['wer']['micro'])}")
    print(f"RTF: {_format_number(summary['rtf'])}")
    print(f"결과: {run_dir}")
    return run_dir


def _evaluate_sample(
    adapter: STTAdapter,
    sample: KcscSample,
    sample_dir: Path,
    model_id: str,
    language: str,
) -> dict[str, Any]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = sample_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    if sample.reference.is_file():
        shutil.copyfile(sample.reference, sample_dir / "reference.txt")

    started = time.perf_counter()
    try:
        references = parse_reference(sample.reference)
        reference_text = " ".join(segment.text for segment in references)
        result = adapter.transcribe(
            TranscriptionRequest(
                audio_path=sample.audio, work_dir=raw_dir, language=language
            )
        )
        comparison = compare(reference_text, result.transcript.text)
        comparison.update(
            {"schema_version": 1, "status": "completed", "sample_id": sample.id}
        )
        audio_seconds = len(result.audio) / SAMPLE_RATE
        transcribe_seconds = float(result.timings.get("transcribe_seconds", 0.0))
        timings = {
            **result.timings,
            "sample_total_seconds": time.perf_counter() - started,
            "rtf": transcribe_seconds / max(audio_seconds, 1e-9),
        }
        prediction = {
            "schema_version": 1,
            "status": "completed",
            "sample_id": sample.id,
            "audio": str(sample.audio),
            "reference": str(sample.reference),
            "model": model_id,
            "adapter": adapter.spec.adapter,
            "checkpoint": adapter.spec.checkpoint,
            "device": result.device,
            "language": result.transcript.language,
            "requested_language": language,
            "duration_seconds": audio_seconds,
            "transcript": result.transcript.text,
            "segments": result.transcript.to_dict()["segments"],
            "timings": timings,
            "engine": result.engine,
            "engine_metadata": result.metadata,
        }
        write_json(sample_dir / "prediction.json", prediction)
        write_json(sample_dir / "comparison.json", comparison)
        write_json(raw_dir / "result.json", result.raw_result)
        (raw_dir / "engine.log").write_text(result.log, encoding="utf-8")
        save_tables(sample_dir, result.transcript)
        write_prediction_markdown(sample_dir / "prediction.md", prediction, comparison)
        return {
            "sample_id": sample.id,
            "status": "completed",
            "device": result.device,
            "audio_seconds": audio_seconds,
            "transcribe_seconds": transcribe_seconds,
            "model_load_seconds": float(result.timings.get("model_load_seconds", 0.0)),
            "character_errors": comparison["character_errors"],
            "reference_characters": comparison["reference_characters"],
            "cer": comparison["cer"],
            "word_errors": comparison["word_errors"],
            "reference_words": comparison["reference_words"],
            "wer": comparison["wer"],
        }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        prediction = {
            "schema_version": 1,
            "status": "failed",
            "sample_id": sample.id,
            "audio": str(sample.audio),
            "reference": str(sample.reference),
            "model": model_id,
            "device": adapter.spec.device,
            "requested_language": language,
            "error": error,
        }
        comparison = {
            "schema_version": 1,
            "status": "not_computed",
            "sample_id": sample.id,
            "error": error,
        }
        write_json(sample_dir / "prediction.json", prediction)
        write_json(sample_dir / "comparison.json", comparison)
        write_prediction_markdown(sample_dir / "prediction.md", prediction, comparison)
        return {
            "sample_id": sample.id,
            "status": "failed",
            "device": adapter.spec.device,
            "error": error,
        }


def write_prediction_markdown(path: Path, prediction: dict, comparison: dict) -> None:
    sample_id = prediction["sample_id"]
    lines = [f"# {sample_id} 전사 결과", ""]
    if prediction["status"] != "completed":
        error = prediction["error"]
        lines.extend(
            [
                "- 상태: 실패",
                f"- 오류: `{error['type']}` — {_single_line(error['message'])}",
                "",
                "CER/WER를 계산하지 못했습니다.",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    lines.extend(
        [
            "- 상태: 완료",
            f"- 모델: `{prediction['model']}`",
            f"- 장치: `{prediction['device']}`",
            f"- CER: `{comparison['cer']:.6f}`",
            f"- WER: `{comparison['wer']:.6f}`",
            f"- RTF: `{prediction['timings']['rtf']:.6f}`",
            "",
            "## 예측 전사",
            "",
            "```text",
        ]
    )
    segments = prediction["segments"]
    if segments:
        for segment in segments:
            speaker = segment.get("speaker") or "unknown"
            text = _single_line(str(segment.get("text", "")))
            lines.append(
                f"[{float(segment.get('start', 0.0)):.3f},{float(segment.get('end', 0.0)):.3f}] "
                f"{speaker} unknown {text}"
            )
    elif prediction.get("transcript"):
        text = _single_line(str(prediction["transcript"]))
        lines.append(
            f"[0.000,{prediction['duration_seconds']:.3f}] unknown unknown {text}"
        )
    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_summary(
    *,
    run_dir: Path,
    records: list[dict[str, Any]],
    model_id: str,
    requested_device: str,
    language: str,
    total_seconds: float,
) -> dict[str, Any]:
    completed = [record for record in records if record["status"] == "completed"]
    failed = [record for record in records if record["status"] == "failed"]
    total_audio_seconds = sum(record["audio_seconds"] for record in completed)
    total_transcribe_seconds = sum(record["transcribe_seconds"] for record in completed)
    return {
        "schema_version": 1,
        "run_id": run_dir.name,
        "status": "completed" if not failed else "completed_with_errors",
        "dataset": "kcsc",
        "model": model_id,
        "requested_device": requested_device,
        "actual_devices": sorted({str(record["device"]) for record in completed}),
        "language": language,
        "total_samples": len(records),
        "completed_samples": len(completed),
        "failed_samples": len(failed),
        "total_audio_seconds": total_audio_seconds,
        "total_transcribe_seconds": total_transcribe_seconds,
        "model_load_seconds": sum(record["model_load_seconds"] for record in completed),
        "total_seconds": total_seconds,
        "rtf": total_transcribe_seconds / max(total_audio_seconds, 1e-9)
        if completed
        else None,
        "cer": _metric_summary(
            completed,
            rate_key="cer",
            error_key="character_errors",
            reference_key="reference_characters",
        ),
        "wer": _metric_summary(
            completed,
            rate_key="wer",
            error_key="word_errors",
            reference_key="reference_words",
        ),
        "samples": records,
    }


def _metric_summary(
    records: list[dict[str, Any]],
    *,
    rate_key: str,
    error_key: str,
    reference_key: str,
) -> dict[str, float | int | None]:
    if not records:
        return {
            "micro": None,
            "macro": None,
            "median": None,
            "errors": 0,
            "reference_units": 0,
        }
    errors = sum(int(record[error_key]) for record in records)
    reference_units = sum(int(record[reference_key]) for record in records)
    rates = [float(record[rate_key]) for record in records]
    return {
        "micro": errors / max(reference_units, 1),
        "macro": statistics.fmean(rates),
        "median": statistics.median(rates),
        "errors": errors,
        "reference_units": reference_units,
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# KCSC ASR 평가 요약",
        "",
        f"- 모델: `{summary['model']}`",
        f"- 요청 장치: `{summary['requested_device']}`",
        f"- 실제 장치: `{', '.join(summary['actual_devices']) or '없음'}`",
        f"- 처리 결과: `{summary['completed_samples']}/{summary['total_samples']}` 성공",
        f"- 전체 CER: `{_format_rate(summary['cer']['micro'])}`",
        f"- 전체 WER: `{_format_rate(summary['wer']['micro'])}`",
        f"- RTF: `{_format_number(summary['rtf'])}`",
        "",
        "## 샘플별 결과",
        "",
        "| 샘플 | 상태 | CER | WER | 오디오(초) | 전사(초) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for record in summary["samples"]:
        if record["status"] == "completed":
            lines.append(
                f"| {record['sample_id']} | 완료 | {record['cer']:.6f} | {record['wer']:.6f} | "
                f"{record['audio_seconds']:.3f} | {record['transcribe_seconds']:.3f} |"
            )
        else:
            message = _single_line(record["error"]["message"]).replace("|", "\\|")
            lines.append(f"| {record['sample_id']} | 실패: {message} | - | - | - | - |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def make_run_id(model_id: str, device: str, started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{timestamp}__kcsc__{safe_name(model_id)}__{safe_name(device)}"


def _find_resume_run(
    project_root: Path,
    model_id: str,
    device: str,
    language: str,
    limit: int | None,
) -> Path:
    runs_dir = project_root / "runs"
    if not runs_dir.is_dir():
        raise FileNotFoundError("이어갈 KCSC 평가 실행이 없습니다.")
    for run_dir in sorted(runs_dir.iterdir(), key=lambda path: path.name, reverse=True):
        run_path = run_dir / "run.json"
        if not run_path.is_file():
            continue
        try:
            payload = _read_json(run_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            payload.get("command") == "evaluate"
            and payload.get("dataset") == "kcsc"
            and payload.get("model") == model_id
            and payload.get("requested_device") == device
            and payload.get("language") == language
            and payload.get("limit") == limit
            and payload.get("status") != "completed"
        ):
            return run_dir
    raise FileNotFoundError("같은 모델·장치·언어로 이어갈 KCSC 평가 실행이 없습니다.")


def _existing_record(sample_dir: Path) -> dict[str, Any] | None:
    prediction_path = sample_dir / "prediction.json"
    comparison_path = sample_dir / "comparison.json"
    if not prediction_path.is_file() or not comparison_path.is_file():
        return None
    try:
        prediction = _read_json(prediction_path)
        comparison = _read_json(comparison_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if (
        prediction.get("status") != "completed"
        or comparison.get("status") != "completed"
    ):
        return None
    timings = prediction.get("timings", {})
    return {
        "sample_id": prediction["sample_id"],
        "status": "completed",
        "device": prediction.get("device", "unknown"),
        "audio_seconds": float(prediction.get("duration_seconds", 0.0)),
        "transcribe_seconds": float(timings.get("transcribe_seconds", 0.0)),
        "model_load_seconds": float(timings.get("model_load_seconds", 0.0)),
        "character_errors": int(comparison["character_errors"]),
        "reference_characters": int(comparison["reference_characters"]),
        "cer": float(comparison["cer"]),
        "word_errors": int(comparison["word_errors"]),
        "reference_words": int(comparison["reference_words"]),
        "wer": float(comparison["wer"]),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 아닙니다: {path}")
    return payload


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _format_rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def _format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"
