"""Run every selected STT model as a sequential evaluation matrix."""

from __future__ import annotations

from datetime import datetime
import gc
import json
import platform
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from sttbench.artifacts import write_json
from sttbench.datasets.kcsc import discover_samples
from sttbench.evaluator import evaluate_kcsc
from sttbench.registry import ModelRegistry


def evaluate_matrix(
    project_root: Path,
    *,
    model_ids: Sequence[str] | None = None,
    devices: Sequence[str] = ("cpu",),
    language: str = "ko",
    limit: int | None = None,
) -> Path:
    samples = discover_samples(project_root / "data" / "kcsc", limit=limit)
    if not samples:
        raise ValueError("평가할 KCSC WAV 파일이 없습니다.")

    registry = ModelRegistry(project_root)
    selected_models = (
        list(model_ids) if model_ids else [spec.id for spec in registry.list()]
    )
    if not selected_models:
        raise ValueError("평가할 모델이 없습니다.")
    for model_id in selected_models:
        registry.get(model_id)

    selected_devices = list(dict.fromkeys(device.lower() for device in devices))
    invalid_devices = [
        device for device in selected_devices if device not in {"cpu", "mps"}
    ]
    if invalid_devices:
        raise ValueError(f"지원하지 않는 장치입니다: {', '.join(invalid_devices)}")
    if not selected_devices:
        raise ValueError("평가할 장치가 없습니다.")

    started_at = datetime.now().astimezone()
    matrix_id = f"{started_at.strftime('%Y%m%d-%H%M%S-%f')[:-3]}__kcsc-matrix"
    matrix_dir = project_root / "runs" / matrix_id
    matrix_dir.mkdir(parents=True, exist_ok=False)
    run_payload = {
        "schema_version": 1,
        "run_id": matrix_id,
        "status": "running",
        "command": "evaluate-all",
        "dataset": "kcsc",
        "models": selected_models,
        "devices": selected_devices,
        "language": language,
        "limit": limit,
        "total_jobs": len(selected_models) * len(selected_devices),
        "started_at": started_at.isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version,
    }
    write_json(matrix_dir / "run.json", run_payload)

    overall_started = time.perf_counter()
    jobs: list[dict[str, Any]] = []
    job_number = 0
    for model_id in selected_models:
        for device in selected_devices:
            job_number += 1
            print(
                f"\n[매트릭스 {job_number}/{run_payload['total_jobs']}] "
                f"{model_id} / {device.upper()}"
            )
            job_started = time.perf_counter()
            try:
                result_dir = evaluate_kcsc(
                    project_root,
                    model_id,
                    device=device,
                    language=language,
                    limit=limit,
                )
                result_summary = _read_json(result_dir / "summary.json")
                jobs.append(
                    {
                        "model": model_id,
                        "requested_device": device,
                        "actual_devices": result_summary.get("actual_devices", []),
                        "status": result_summary["status"],
                        "run_dir": str(result_dir),
                        "completed_samples": result_summary["completed_samples"],
                        "failed_samples": result_summary["failed_samples"],
                        "cer": result_summary["cer"]["micro"],
                        "wer": result_summary["wer"]["micro"],
                        "rtf": result_summary["rtf"],
                        "seconds": time.perf_counter() - job_started,
                    }
                )
            except Exception as exc:
                jobs.append(
                    {
                        "model": model_id,
                        "requested_device": device,
                        "actual_devices": [],
                        "status": "failed",
                        "run_dir": None,
                        "completed_samples": 0,
                        "failed_samples": len(samples),
                        "cer": None,
                        "wer": None,
                        "rtf": None,
                        "seconds": time.perf_counter() - job_started,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                )
                print(f"실패: {type(exc).__name__}: {exc}")
            finally:
                release_model_memory()

    total_seconds = time.perf_counter() - overall_started
    failed_jobs = sum(job["status"] == "failed" for job in jobs)
    partial_jobs = sum(job["status"] == "completed_with_errors" for job in jobs)
    summary = {
        **run_payload,
        "status": "completed"
        if not failed_jobs and not partial_jobs
        else "completed_with_errors",
        "completed_jobs": len(jobs) - failed_jobs,
        "failed_jobs": failed_jobs,
        "partial_jobs": partial_jobs,
        "total_seconds": total_seconds,
        "jobs": jobs,
        "best_cer": _best_job(jobs, "cer"),
        "best_wer": _best_job(jobs, "wer"),
        "fastest_rtf": _best_job(jobs, "rtf"),
    }
    write_json(matrix_dir / "summary.json", summary)
    write_summary_markdown(matrix_dir / "summary.md", summary)
    write_json(
        matrix_dir / "run.json",
        {
            **run_payload,
            "status": summary["status"],
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "summary": str(matrix_dir / "summary.json"),
        },
    )
    print(
        f"\n전체 모델 평가 완료: {summary['completed_jobs']}/{summary['total_jobs']}개 조합 실행"
    )
    print(f"매트릭스 결과: {matrix_dir}")
    return matrix_dir


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# KCSC 모델·장치 평가 매트릭스",
        "",
        f"- 모델 수: `{len(summary['models'])}`",
        f"- 장치: `{', '.join(summary['devices'])}`",
        f"- 실행 조합: `{summary['completed_jobs']}/{summary['total_jobs']}` 완료",
        "",
        "| 모델 | 요청 장치 | 실제 장치 | 상태 | CER | WER | RTF | 실행 결과 |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for job in summary["jobs"]:
        actual = ", ".join(job["actual_devices"]) or "-"
        run_dir = f"`{job['run_dir']}`" if job["run_dir"] else "-"
        status = job["status"]
        if job.get("error"):
            message = _single_line(job["error"]["message"]).replace("|", "\\|")
            status = f"실패: {message}"
        lines.append(
            f"| {job['model']} | {job['requested_device']} | {actual} | {status} | "
            f"{_format_metric(job['cer'])} | {_format_metric(job['wer'])} | "
            f"{_format_metric(job['rtf'], digits=4)} | {run_dir} |"
        )
    lines.append("")
    for label, key in (
        ("최저 CER", "best_cer"),
        ("최저 WER", "best_wer"),
        ("최고 속도", "fastest_rtf"),
    ):
        best = summary[key]
        if best:
            lines.append(
                f"- {label}: `{best['model']}` / `{best['requested_device']}` "
                f"(`{best['value']:.6f}`)"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def release_model_memory() -> None:
    gc.collect()
    try:
        import torch

        if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
    except (ImportError, RuntimeError):
        pass


def _best_job(jobs: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    candidates = [job for job in jobs if job.get(metric) is not None]
    if not candidates:
        return None
    best = min(candidates, key=lambda job: float(job[metric]))
    return {
        "model": best["model"],
        "requested_device": best["requested_device"],
        "actual_devices": best["actual_devices"],
        "value": float(best[metric]),
        "run_dir": best["run_dir"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 아닙니다: {path}")
    return payload


def _format_metric(value: float | None, *, digits: int = 6) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _single_line(value: str) -> str:
    return " ".join(value.split())
