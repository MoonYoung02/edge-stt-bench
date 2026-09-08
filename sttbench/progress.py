"""Progress reporting and history-based runtime estimates."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def format_elapsed(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}시간 {minutes}분 {remainder:.2f}초"
    if minutes:
        return f"{minutes}분 {remainder:.2f}초"
    return f"{seconds:.2f}초"


def probe_audio_duration(path: Path) -> float | None:
    executable = shutil.which("ffprobe")
    if executable is None:
        return None
    process = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        return None
    try:
        return float(process.stdout.strip())
    except ValueError:
        return None


def runtime_estimate(
    project_root: Path,
    model_id: str,
    audio_seconds: float | None,
    *,
    diarize: bool = False,
) -> dict:
    estimate: dict[str, object] = {
        "audio_seconds": audio_seconds,
        "estimated_total_seconds": None,
        "basis": None,
    }
    if audio_seconds is None:
        return estimate

    candidates = list((project_root / "runs").glob("**/summary.json"))
    candidates.extend((project_root / "results" / "inspect").glob("*/run_summary.json"))
    history: list[tuple[float, Path, dict]] = []
    for summary_path in candidates:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            previous_audio = float(summary.get("audio_seconds") or 0)
        except (OSError, ValueError, TypeError):
            continue
        if (
            summary.get("model") != model_id
            or bool(summary.get("diarization")) != diarize
            or previous_audio <= 0
        ):
            continue
        history.append((summary_path.stat().st_mtime, summary_path, summary))
    if not history:
        return estimate

    _mtime, summary_path, summary = max(history, key=lambda item: item[0])
    timings = summary.get("timings", {}) if isinstance(summary.get("timings"), dict) else {}
    inference = (
        timings.get("transcribe_seconds")
        or summary.get("transcribe_seconds")
        or summary.get("model_load_and_transcribe_seconds")
    )
    total = timings.get("total_seconds") or summary.get("total_seconds")
    if inference is None or total is None:
        return estimate
    previous_audio = float(summary["audio_seconds"])
    fixed_overhead = max(0.0, float(total) - float(inference))
    estimated_total = fixed_overhead + float(inference) / previous_audio * audio_seconds
    estimate.update(
        {
            "estimated_total_seconds": estimated_total,
            "basis": str(summary_path),
            "basis_audio_seconds": previous_audio,
            "basis_total_seconds": float(total),
        }
    )
    return estimate


def show_runtime_estimate(
    project_root: Path,
    path: Path,
    model_id: str,
    *,
    diarize: bool = False,
) -> dict:
    estimate = runtime_estimate(
        project_root, model_id, probe_audio_duration(path), diarize=diarize
    )
    audio_seconds = estimate["audio_seconds"]
    print(
        f"음성 길이: {format_elapsed(float(audio_seconds))}"
        if audio_seconds is not None
        else "음성 길이: 확인할 수 없음"
    )
    predicted = estimate["estimated_total_seconds"]
    if predicted is None:
        print("예상 전체 실행 시간: 이전 동일 모델 기록 없음")
    else:
        print(f"예상 전체 실행 시간: 약 {format_elapsed(float(predicted))} (최근 기록 기준)")
    return estimate


def run_process_with_progress(command: list[str]) -> tuple[int, str, float]:
    """Run whisper.cpp and turn its progress lines into a stable Korean display."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = bytearray()
    last_progress = -1
    try:
        assert process.stdout is not None
        for raw_line in iter(process.stdout.readline, b""):
            output.extend(raw_line)
            match = re.search(r"progress\s*=\s*(\d+)%", raw_line.decode("utf-8", errors="replace"))
            if not match:
                continue
            progress = min(100, int(match.group(1)))
            if progress == last_progress:
                continue
            last_progress = progress
            elapsed = time.perf_counter() - started
            remaining = elapsed * (100 - progress) / progress if progress else 0.0
            print(
                f"\rSTT 진행: {progress:3d}% | 경과 {format_elapsed(elapsed)} | "
                f"남은 시간 약 {format_elapsed(remaining)}",
                end="",
                flush=True,
            )
        returncode = process.wait()
    except BaseException:
        process.terminate()
        process.wait()
        raise
    elapsed = time.perf_counter() - started
    if returncode == 0 and last_progress < 100:
        print(f"\rSTT 진행: 100% | 경과 {format_elapsed(elapsed)} | 남은 시간 약 0.00초", end="")
    if last_progress >= 0 or returncode == 0:
        print()
    return returncode, output.decode("utf-8", errors="replace"), elapsed
