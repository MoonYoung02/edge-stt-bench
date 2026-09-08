#!/usr/bin/env python3
"""Score EdgeSTT Mobile Bench automatic batches with sttbench's CER/WER.

The Flutter app's "정답지 있는 샘플 전체 자동 실행" batch feature
(`BenchmarkCoordinator.runBatch` in lib/src/benchmark_coordinator.dart) runs
one whisper.cpp inference per labeled KCSC sample and saves each as an
ordinary run JSON (same shape as a manual run, plus `batchId`/`sampleId`)
under the app's `files/results/` directory, alongside an optional
`files/results/batches/<batchId>.json` batch record.

This script does NOT reimplement CER/WER in Dart. It reads those exported
run JSON files, groups them by `batchId`, and scores each completed run's
`result.transcript` against `result.reference` with the exact same text
normalization and edit-distance implementation the desktop `sttbench`
evaluator uses (`sttbench.metrics.text.compare`), so mobile and desktop
accuracy numbers are computed identically. See docs/BENCHMARK_PROTOCOL.md §8.

Getting the run JSON files onto disk:

    ./tools/pull_benchmark_results.sh                 # debug build, adb pull
    # or: press "내보내기" per run, then adb pull the Downloads folder

Usage:

    python3 tools/mobile_result_importer.py <run-json-dir-or-file> [--output DIR]

Writes, per batch:

    <output>/<batchId>/summary.json
    <output>/<batchId>/summary.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

# sttbench lives at the repo root, two levels above this file
# (mobile_bench/tools/mobile_result_importer.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sttbench.datasets.kcsc import parse_reference_text  # noqa: E402
from sttbench.metrics.text import compare  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score EdgeSTT Mobile Bench results with the desktop CER/WER "
            "implementation."
        )
    )
    parser.add_argument(
        "input", type=Path, help="run JSON file, or a directory searched recursively"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "benchmark-results",
        help="output root directory (default: mobile_bench/benchmark-results)",
    )
    return parser.parse_args()


def find_json_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.rglob("*.json"))


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def is_run_file(payload: dict[str, Any]) -> bool:
    return "runId" in payload and "sampleAssetPath" in payload


def is_batch_file(payload: dict[str, Any]) -> bool:
    return "batchId" in payload and "entries" in payload


def main() -> None:
    args = parse_args()
    files = find_json_files(args.input)
    if not files:
        raise SystemExit(f"JSON 파일을 찾지 못했습니다: {args.input}")

    runs_by_batch: dict[str, list[dict[str, Any]]] = {}
    batch_meta: dict[str, dict[str, Any]] = {}
    unbatched_run_count = 0
    seen_run_ids: set[str] = set()
    duplicate_count = 0

    for path in files:
        payload = load_json(path)
        if payload is None:
            continue
        if is_batch_file(payload):
            batch_meta[str(payload["batchId"])] = payload
        elif is_run_file(payload):
            # The app's export/Downloads flow can leave the same runId
            # exported twice (e.g. Android suffixing a re-export
            # "... (1).json" instead of overwriting) — keep the first copy
            # seen, or a sample gets scored twice under one batch.
            run_id = payload["runId"]
            if run_id in seen_run_ids:
                duplicate_count += 1
                continue
            seen_run_ids.add(run_id)
            batch_id = payload.get("batchId")
            if batch_id:
                runs_by_batch.setdefault(str(batch_id), []).append(payload)
            else:
                unbatched_run_count += 1

    if duplicate_count:
        print(f"참고: 같은 runId가 중복 발견돼 {duplicate_count}개 파일을 건너뛰었습니다.")

    if not runs_by_batch:
        raise SystemExit(
            "batchId가 있는 실행 결과를 찾지 못했습니다. "
            "'전체 자동 실행'으로 만든 결과가 맞는지 확인하세요."
        )

    for batch_id, runs in sorted(runs_by_batch.items()):
        summary = build_batch_summary(batch_id, runs, batch_meta.get(batch_id))
        output_dir = args.output / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "summary.json", summary)
        write_summary_markdown(output_dir / "summary.md", summary)
        print(
            f"{batch_id}: {summary['completed_samples']}/{summary['total_samples']}개 "
            f"채점 완료 → {output_dir}"
        )
        print(f"  CER {_format_rate(summary['cer']['micro'])}  "
              f"WER {_format_rate(summary['wer']['micro'])}  "
              f"RTF {_format_number(summary['rtf'])}")

    if unbatched_run_count:
        print(
            f"참고: batchId가 없는 실행 결과 {unbatched_run_count}개는 "
            "건너뛰었습니다(수동 단일 실행)."
        )


def build_batch_summary(
    batch_id: str,
    runs: list[dict[str, Any]],
    batch_meta_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    runs = sorted(runs, key=lambda run: run.get("sampleId") or run.get("sampleAssetPath", ""))
    records = [score_run(run) for run in runs]
    completed = [record for record in records if record["status"] == "completed"]
    total_audio_seconds = sum(record["audio_seconds"] for record in completed)
    total_inference_seconds = sum(record["inference_seconds"] for record in completed)

    first_run = runs[0]
    device = first_run.get("device") or {}
    summary: dict[str, Any] = {
        "schema_version": 1,
        "source": "mobile_bench",
        "batch_id": batch_id,
        "model_id": first_run.get("modelId"),
        "threads": first_run.get("threads"),
        "device": {
            "platform": device.get("platform"),
            "manufacturer": device.get("manufacturer"),
            "model": device.get("model"),
            "osVersion": device.get("osVersion"),
        },
        "total_samples": len(records),
        "completed_samples": len(completed),
        "failed_samples": len(records) - len(completed),
        "total_audio_seconds": total_audio_seconds,
        "total_inference_seconds": total_inference_seconds,
        "rtf": total_inference_seconds / total_audio_seconds
        if total_audio_seconds
        else None,
        "cer": _metric_summary(completed, "cer", "character_errors", "reference_characters"),
        "wer": _metric_summary(completed, "wer", "word_errors", "reference_words"),
        "samples": records,
    }

    if batch_meta_payload is not None:
        entries = batch_meta_payload.get("entries", [])
        summary["planned_samples"] = len(entries)
        summary["skipped_samples"] = [
            entry["sampleId"] for entry in entries if entry.get("status") == "skipped"
        ]
        summary["thermal_throttled_samples"] = [
            entry["sampleId"] for entry in entries if entry.get("thermalThrottled")
        ]

    return summary


def score_run(run: dict[str, Any]) -> dict[str, Any]:
    sample_id = Path(run.get("sampleId") or run.get("sampleAssetPath", "")).stem
    result = run.get("result")
    if run.get("status") != "completed" or not result:
        return {
            "sample_id": sample_id,
            "status": run.get("status", "unknown"),
            "run_id": run.get("runId"),
            "error": run.get("error"),
        }

    reference_raw = result.get("reference")
    if not reference_raw:
        return {
            "sample_id": sample_id,
            "status": "no_reference",
            "run_id": run.get("runId"),
        }

    # `result.reference` is the raw KCSC TXT the app bundled as an asset
    # (`[start,end]\tspeaker\tgender\ttext` per line, see docs/DATASET.md),
    # not plain text. Extract just the text column the same way the desktop
    # evaluator does, or CER/WER would be scored against timestamp/speaker
    # columns instead of the transcript.
    try:
        reference = " ".join(
            segment.text for segment in parse_reference_text(reference_raw, source=sample_id)
        )
    except ValueError:
        reference = reference_raw

    transcript = result.get("transcript", "")
    comparison = compare(reference, transcript)
    audio_seconds = (result.get("audioDurationMs") or 0) / 1000
    inference_seconds = (result.get("processingTimeMs") or 0) / 1000
    return {
        "sample_id": sample_id,
        "status": "completed",
        "run_id": run.get("runId"),
        "audio_seconds": audio_seconds,
        "inference_seconds": inference_seconds,
        "rtf": inference_seconds / audio_seconds if audio_seconds else None,
        "character_errors": comparison["character_errors"],
        "reference_characters": comparison["reference_characters"],
        "cer": comparison["cer"],
        "word_errors": comparison["word_errors"],
        "reference_words": comparison["reference_words"],
        "wer": comparison["wer"],
        "maximum_thermal_status": (run.get("summary") or {}).get("maximumThermalStatus"),
    }


def _metric_summary(
    records: list[dict[str, Any]],
    rate_key: str,
    error_key: str,
    reference_key: str,
) -> dict[str, float | int | None]:
    if not records:
        return {"micro": None, "macro": None, "median": None, "errors": 0, "reference_units": 0}
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    device = summary["device"]
    device_label = " ".join(
        part for part in [device.get("manufacturer"), device.get("model")] if part
    ) or "알 수 없음"
    lines = [
        f"# 모바일 자동 벤치마크 요약 — {summary['batch_id']}",
        "",
        f"- 모델: `{summary['model_id']}`",
        f"- threads: `{summary['threads']}`",
        f"- 기기: `{device_label}` ({device.get('osVersion') or '알 수 없음'})",
        f"- 처리 결과: `{summary['completed_samples']}/{summary['total_samples']}` 채점 완료",
        f"- 전체 CER: `{_format_rate(summary['cer']['micro'])}`",
        f"- 전체 WER: `{_format_rate(summary['wer']['micro'])}`",
        f"- RTF: `{_format_number(summary['rtf'])}`",
    ]
    if summary.get("skipped_samples"):
        lines.append(f"- 건너뛴 샘플: {', '.join(summary['skipped_samples'])}")
    if summary.get("thermal_throttled_samples"):
        lines.append(
            f"- ⚠️ 발열 상태에서 측정된 샘플(RTF 신뢰 낮음): "
            f"{', '.join(summary['thermal_throttled_samples'])}"
        )
    lines += [
        "",
        "## 샘플별 결과",
        "",
        "| 샘플 | 상태 | CER | WER | RTF | 최고 발열 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for record in summary["samples"]:
        if record["status"] == "completed":
            lines.append(
                f"| {record['sample_id']} | 완료 | {record['cer']:.6f} | "
                f"{record['wer']:.6f} | {_format_number(record['rtf'])} | "
                f"{record.get('maximum_thermal_status') or '-'} |"
            )
        else:
            lines.append(f"| {record['sample_id']} | {record['status']} | - | - | - | - |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _format_rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def _format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    main()
