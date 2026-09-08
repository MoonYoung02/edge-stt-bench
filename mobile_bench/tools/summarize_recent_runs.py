#!/usr/bin/env python3
"""Combine the most recently started `runs/<run_id>/` directories into one
KCSC ASR summary markdown, in the exact same format as a single desktop or
mobile run's `summary.md` (reuses `build_summary`/`write_summary_markdown`
from `sttbench.evaluator` directly).

Since `mobile_to_runs.py` now writes one run directory per sample (never
grouped by `batchId`), this is how you get one combined report back across
however many of those you want — e.g. "the last 15 mobile runs" — without
having to open each `summary.md` individually.

Usage:

    python3 tools/summarize_recent_runs.py --recent 15
    python3 tools/summarize_recent_runs.py --recent 15 --model whisper-small-q8_0-no-context
    python3 tools/summarize_recent_runs.py --recent 15 --output ./benchmark-results/recent-15-summary.md

Recency is each run's own `run.json` "started_at" (when the STT run actually
happened), not the run directory's filesystem mtime — so this stays correct
even if directories were copied, re-pulled, or converted out of order.
`--recent N` keeps only the N most recently *started* runs; omit it to
combine every run directory found. `--model` restricts to one model id first,
useful when `--runs-dir` holds a mix of models (the default does, once you've
tested more than one). Duplicate sample ids across the selected runs (e.g. a
sample re-run twice) are not deduplicated — both rows are kept, same as
opening both `summary.md` files separately would show.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# sttbench lives at the repo root, two levels above this file
# (mobile_bench/tools/summarize_recent_runs.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from sttbench.evaluator import build_summary, write_summary_markdown  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine the most recently started runs/ directories into one KCSC summary.md"
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "benchmark-results" / "runs",
        help="run directories root (default: mobile_bench/benchmark-results/runs)",
    )
    parser.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="run.json의 started_at 기준 가장 최근 실행 N개만 합칩니다(생략하면 전체).",
    )
    parser.add_argument(
        "--model",
        help="이 모델 id의 실행만 포함합니다(생략하면 발견된 모든 모델 포함).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "결과 markdown 저장 경로(생략하면 "
            "<runs-dir 상위>/recent-<N>[-<모델>]-summary.md에 저장)"
        ),
    )
    args = parser.parse_args()
    if args.recent is not None and args.recent < 1:
        parser.error("--recent는 1 이상이어야 합니다.")
    return args


def find_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return sorted(
        path
        for path in runs_dir.iterdir()
        if path.is_dir()
        and (path / "run.json").is_file()
        and (path / "summary.json").is_file()
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _started_at(run_dir: Path) -> str:
    try:
        payload = load_json(run_dir / "run.json")
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("started_at") or "")


def main() -> None:
    args = parse_args()
    run_dirs = find_run_dirs(args.runs_dir)
    if not run_dirs:
        raise SystemExit(f"실행 폴더를 찾지 못했습니다: {args.runs_dir}")

    candidates = []
    for run_dir in run_dirs:
        summary = load_json(run_dir / "summary.json")
        if args.model and summary.get("model") != args.model:
            continue
        candidates.append((run_dir, summary))
    if not candidates:
        raise SystemExit(f"모델 '{args.model}'의 실행을 찾지 못했습니다: {args.runs_dir}")

    # Most recently *started* first, keyed on run.json's started_at rather
    # than directory mtime or name, so this is correct regardless of when the
    # files happened to land on this machine.
    candidates.sort(key=lambda pair: _started_at(pair[0]), reverse=True)
    if args.recent is not None:
        candidates = candidates[: args.recent]

    records: list[dict[str, Any]] = []
    models: set[str] = set()
    devices: set[str] = set()
    total_seconds = 0.0
    for run_dir, summary in candidates:
        records.extend(summary.get("samples", []))
        models.add(str(summary.get("model", "unknown")))
        devices.update(
            summary.get("actual_devices")
            or [str(summary.get("requested_device", "unknown"))]
        )
        total_seconds += float(summary.get("total_seconds") or 0.0)

    model_label = next(iter(models)) if len(models) == 1 else " / ".join(sorted(models))
    device_label = (
        next(iter(devices)) if len(devices) == 1 else " / ".join(sorted(devices))
    )

    combined = build_summary(
        run_dir=Path(f"recent-{len(candidates)}-runs"),
        records=records,
        model_id=model_label,
        requested_device=device_label,
        language="ko",
        total_seconds=total_seconds,
    )

    output_path = args.output
    if output_path is None:
        suffix = f"-{args.model}" if args.model else ""
        output_path = (
            args.runs_dir.parent / f"recent-{len(candidates)}{suffix}-summary.md"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_summary_markdown(output_path, combined)

    included = ", ".join(run_dir.name for run_dir, _ in candidates)
    print(f"{len(candidates)}개 실행 합산 → {output_path}")
    print(f"포함된 실행: {included}")
    print(output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
