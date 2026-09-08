#!/usr/bin/env python3
"""Convert exported STT Mobile Bench results into the desktop `runs/` layout.

`sttbench/evaluator.py`'s `evaluate_kcsc` writes each desktop evaluation as:

    runs/<run_id>/
      run.json
      summary.json
      summary.md
      samples/<sample_id>/
        reference.txt
        prediction.json
        prediction.md
        comparison.json

This script builds the exact same layout from mobile run JSON exports (one
whisper.cpp run per KCSC sample, produced by the app's "정답지 있는 샘플
전체 자동 실행" batch feature or by manual single runs), reusing
`build_summary`/`write_summary_markdown`/`write_prediction_markdown` from
`sttbench.evaluator` and `compare`/`parse_reference_text` from `sttbench`
directly — so a mobile run reads exactly like a desktop one and both can be
skimmed or diffed the same way.

Getting the run JSON files onto disk first:

    ./tools/pull_benchmark_results.sh                 # debug build, adb pull
    # or: export each run from its result screen, then adb pull Downloads

Usage:

    python3 tools/mobile_to_runs.py <run-json-dir-or-file> [--runs-dir DIR] [--recent N]

`--recent N` limits the conversion to the N most recently modified JSON files
in the input directory (by file mtime) instead of everything found — handy
right after `pull_benchmark_results.sh --recent N` when the results folder has
accumulated many older runs you don't want to re-convert.

Every run JSON file — whether it came from the app's batch auto-run or a
manual single run — becomes its own `<runs-dir>/<run_id>/` directory with
exactly one sample inside. Samples are never grouped by `batchId`: even 22
files sharing one batch produce 22 separate run directories, so pulling only
some of a batch (e.g. via `--recent N`) never leaves a run "missing" samples
that exist elsewhere on disk. `batchId` (when present) is still recorded in
each run's `run.json` under `mobile_source.batch_id` so you can tell which
batch a given sample came from. Default `--runs-dir` is
`mobile_bench/benchmark-results/runs`, kept separate from the desktop
project's own `runs/` at the repo root — pass `--runs-dir ../runs` (or an
absolute path to it) to merge mobile results directly alongside desktop ones.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# sttbench lives at the repo root, two levels above this file
# (mobile_bench/tools/mobile_to_runs.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from sttbench.artifacts import write_json  # noqa: E402
from sttbench.datasets.kcsc import parse_reference_text  # noqa: E402
from sttbench.evaluator import (  # noqa: E402
    build_summary,
    write_summary_markdown,
    write_prediction_markdown,
)
from sttbench.metrics.text import compare  # noqa: E402
from sttbench.runner import safe_name  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert STT Mobile Bench run JSON into the desktop runs/ layout."
    )
    parser.add_argument(
        "input", type=Path, help="run JSON file, or a directory searched recursively"
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "benchmark-results" / "runs",
        help="output root, one subdirectory per run (default: mobile_bench/benchmark-results/runs)",
    )
    parser.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help=(
            "가장 최근 수정된 N개 JSON 파일만 변환합니다(파일 mtime 기준). "
            "batchId로 묶이는 배치 실행 중 일부 샘플 파일만 골라질 수 있습니다."
        ),
    )
    args = parser.parse_args()
    if args.recent is not None and args.recent < 1:
        parser.error("--recent는 1 이상이어야 합니다.")
    return args


def find_json_files(input_path: Path, *, recent: int | None = None) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    files = sorted(input_path.rglob("*.json"))
    if recent is None:
        return files
    # Sort by modification time, newest first, then keep only the top N —
    # mirrors pull_benchmark_results.sh's --recent (device mtime order).
    files_by_mtime = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
    return files_by_mtime[:recent]


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_run_file(payload: dict[str, Any]) -> bool:
    return "runId" in payload and "sampleAssetPath" in payload


def main() -> None:
    args = parse_args()
    files = find_json_files(args.input, recent=args.recent)
    if not files:
        raise SystemExit(f"JSON 파일을 찾지 못했습니다: {args.input}")
    if args.recent is not None:
        print(f"최근 수정된 {len(files)}개 파일만 변환합니다(--recent {args.recent}).")

    groups: dict[str, list[dict[str, Any]]] = {}
    seen_run_ids: set[str] = set()
    duplicate_count = 0
    for path in files:
        payload = load_json(path)
        if payload is None or not is_run_file(payload):
            continue
        # The app's export/Downloads flow can leave the same runId exported
        # twice (e.g. Android suffixing a re-export "... (1).json" instead of
        # overwriting) — keep the first copy seen and skip the rest, or a
        # sample would be scored twice under one run.
        run_id = payload["runId"]
        if run_id in seen_run_ids:
            duplicate_count += 1
            continue
        seen_run_ids.add(run_id)
        # Every run JSON becomes its own one-sample "run" directory, same as
        # desktop's --limit 1 — never grouped by batchId. Grouping by batchId
        # used to combine same-batch samples into one run directory, but that
        # meant a partial pull (e.g. --recent N cutting into a batch) silently
        # produced a run "missing" samples that were actually just elsewhere
        # on disk. One file in, one run directory out avoids that entirely.
        key = f"single-{run_id}"
        groups.setdefault(key, []).append(payload)

    if duplicate_count:
        print(f"참고: 같은 runId가 중복 발견돼 {duplicate_count}개 파일을 건너뛰었습니다.")

    if not groups:
        raise SystemExit(f"변환할 실행 결과를 찾지 못했습니다: {args.input}")

    args.runs_dir.mkdir(parents=True, exist_ok=True)
    for _key, runs in sorted(groups.items(), key=lambda kv: _group_sort_key(kv[1])):
        convert_group(runs, args.runs_dir)


# Ordered coarsest-to-finest so a substring check on the model id finds the
# right bucket; "large" must stay last since it's a substring of nothing else
# here but "large-v3-turbo" would also match "large" fine.
_MODEL_SIZE_ORDER = ["tiny", "base", "small", "medium", "large"]
_QUANTIZATION_PATTERN = re.compile(r"q(\d+)_(\d+|k)", re.IGNORECASE)


def _group_sort_key(runs: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Sorts groups by model size, then quantization level (bit-width, then
    the `_0`/`_1`/`_k` variant) — not by when they happened to be run, since
    a model tested many times over a day is scattered across the day
    otherwise. Falls back to the model id and earliest `startedAt` so the
    order stays fully deterministic beyond that."""
    model_id = str((runs[0].get("modelId") or "")).lower()
    size_rank = next(
        (index for index, size in enumerate(_MODEL_SIZE_ORDER) if size in model_id),
        len(_MODEL_SIZE_ORDER),
    )
    match = _QUANTIZATION_PATTERN.search(model_id)
    if match:
        bits = int(match.group(1))
        variant = match.group(2).lower()
        variant_rank = {"0": 0, "1": 1}.get(variant, 2)  # q*_0 < q*_1 < q*_k
    else:
        bits = 0
        variant_rank = -1  # unquantized sorts before its quantized variants
    started_at = min((run.get("startedAt") or "") for run in runs)
    return (size_rank, bits, variant_rank, model_id, started_at)


def _mobile_run_id(model_id: str, device_label: str, started_at: datetime) -> str:
    """`{model}__kcsc__{device}__{timestamp}` — unlike desktop's
    `make_run_id` (timestamp first), the model+quantization leads so run
    folders sorted alphabetically group by model first, matching the
    model-size-then-quantization order `_group_sort_key` already processes
    them in."""
    timestamp = started_at.strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{safe_name(model_id)}__kcsc__{safe_name(device_label)}__{timestamp}"


def convert_group(runs: list[dict[str, Any]], runs_dir: Path) -> None:
    runs = sorted(runs, key=lambda run: run.get("sampleId") or run.get("sampleAssetPath", ""))
    first = runs[0]
    model_id = str(first.get("modelId", "unknown-model"))
    device_info = first.get("device") or {}
    device_label = safe_name(f"android-{device_info.get('model') or 'device'}")
    started_at = _parse_dt(first.get("startedAt")) or datetime.now(timezone.utc)

    run_id = _mobile_run_id(model_id, device_label, started_at)
    run_dir = runs_dir / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = runs_dir / f"{run_id}-{suffix}"
        suffix += 1
    run_id = run_dir.name
    run_dir.mkdir(parents=True)

    records = [convert_sample(run, run_dir, model_id, device_label) for run in runs]
    total_seconds = sum(
        record.get("transcribe_seconds", 0.0)
        for record in records
        if record["status"] == "completed"
    )

    summary = build_summary(
        run_dir=run_dir,
        records=records,
        model_id=model_id,
        requested_device=device_label,
        language="ko",
        total_seconds=total_seconds,
    )
    write_json(run_dir / "summary.json", summary)
    write_summary_markdown(run_dir / "summary.md", summary)

    finished_at = _parse_dt(runs[-1].get("completedAt")) or datetime.now(timezone.utc)
    write_json(
        run_dir / "run.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": summary["status"],
            "command": "mobile-import",
            "dataset": "kcsc",
            "dataset_root": None,
            "model": model_id,
            "adapter": "mobile_bench",
            "checkpoint": model_id,
            "requested_device": device_label,
            "language": "ko",
            "limit": len(records),
            "started_at": started_at.isoformat(timespec="seconds"),
            "resumed_at": None,
            "platform": f"{device_info.get('platform', 'android')} "
            f"{device_info.get('manufacturer', '')} {device_info.get('model', '')} "
            f"({device_info.get('osVersion', '')})".strip(),
            "python": None,
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "actual_devices": summary["actual_devices"],
            "summary": str(run_dir / "summary.json"),
            "mobile_source": {
                "batch_id": first.get("batchId"),
                "threads": first.get("threads"),
                "device": device_info,
            },
        },
    )
    print(
        f"{run_id}: {summary['completed_samples']}/{summary['total_samples']}개 변환 → {run_dir}"
    )


def convert_sample(
    run: dict[str, Any], run_dir: Path, model_id: str, device_label: str
) -> dict[str, Any]:
    sample_id = safe_name(Path(run.get("sampleId") or run.get("sampleAssetPath", "")).stem)
    sample_dir = run_dir / "samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    result = run.get("result")

    reference_text = ""
    if result and result.get("reference"):
        # `result.reference` is the raw KCSC TXT the app bundled as an asset
        # (`[start,end]\tspeaker\tgender\ttext` per line), not plain text —
        # extract the text column the same way the desktop evaluator does.
        try:
            reference_text = " ".join(
                segment.text
                for segment in parse_reference_text(result["reference"], source=sample_id)
            )
        except ValueError:
            reference_text = result["reference"]

    if run.get("status") != "completed" or not result:
        error = {
            "type": "MobileRunError",
            "message": run.get("error") or f"실행 상태: {run.get('status', 'unknown')}",
        }
    elif not reference_text:
        error = {"type": "NoReferenceError", "message": "정답 텍스트가 없어 CER/WER을 계산할 수 없습니다."}
    else:
        error = None

    if error is not None:
        prediction = {
            "schema_version": 1,
            "status": "failed",
            "sample_id": sample_id,
            "audio": run.get("sampleAssetPath"),
            "model": model_id,
            "device": device_label,
            "requested_language": "ko",
            "error": error,
        }
        comparison = {
            "schema_version": 1,
            "status": "not_computed",
            "sample_id": sample_id,
            "error": error,
        }
        write_json(sample_dir / "prediction.json", prediction)
        write_json(sample_dir / "comparison.json", comparison)
        write_prediction_markdown(sample_dir / "prediction.md", prediction, comparison)
        return {"sample_id": sample_id, "status": "failed", "device": device_label, "error": error}

    (sample_dir / "reference.txt").write_text(reference_text + "\n", encoding="utf-8")
    transcript = result.get("transcript", "")
    comparison = compare(reference_text, transcript)
    comparison.update({"schema_version": 1, "status": "completed", "sample_id": sample_id})
    write_json(sample_dir / "comparison.json", comparison)

    audio_seconds = (result.get("audioDurationMs") or 0) / 1000
    transcribe_seconds = (result.get("processingTimeMs") or 0) / 1000
    rtf = transcribe_seconds / audio_seconds if audio_seconds else 0.0
    segments = [
        {
            "start": (segment.get("fromMs") or 0) / 1000,
            "end": (segment.get("toMs") or 0) / 1000,
            "text": segment.get("text", ""),
        }
        for segment in result.get("transcriptSegments", [])
    ]

    prediction = {
        "schema_version": 1,
        "status": "completed",
        "sample_id": sample_id,
        "audio": run.get("sampleAssetPath"),
        "reference": None,
        "model": model_id,
        "adapter": "mobile_bench",
        "checkpoint": model_id,
        "device": device_label,
        "language": "ko",
        "requested_language": "ko",
        "duration_seconds": audio_seconds,
        "transcript": transcript,
        "segments": segments,
        "timings": {
            "transcribe_seconds": transcribe_seconds,
            "staging_seconds": (result.get("stagingTimeMs") or 0) / 1000,
            "model_load_seconds": 0.0,
            "rtf": rtf,
        },
        "engine": "whisper.cpp",
        "engine_metadata": {
            "threads": run.get("threads"),
            "raw_device": run.get("device"),
            "maximum_thermal_status": (run.get("summary") or {}).get("maximumThermalStatus"),
        },
    }
    write_json(sample_dir / "prediction.json", prediction)
    write_prediction_markdown(sample_dir / "prediction.md", prediction, comparison)

    return {
        "sample_id": sample_id,
        "status": "completed",
        "device": device_label,
        "audio_seconds": audio_seconds,
        "transcribe_seconds": transcribe_seconds,
        "model_load_seconds": 0.0,
        "character_errors": comparison["character_errors"],
        "reference_characters": comparison["reference_characters"],
        "cer": comparison["cer"],
        "word_errors": comparison["word_errors"],
        "reference_words": comparison["reference_words"],
        "wer": comparison["wer"],
    }


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


if __name__ == "__main__":
    main()
