#!/usr/bin/env python3
"""Convert STT benchmark JSON files into readable Markdown reports."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


KST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert benchmark JSON to Markdown")
    parser.add_argument("input", type=Path, help="JSON file or directory")
    parser.add_argument("--output", type=Path, help="output directory")
    return parser.parse_args()


def number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def fmt(value: Optional[float], digits: int = 2, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def duration_seconds(milliseconds: Any) -> Optional[float]:
    value = number(milliseconds)
    return None if value is None else value / 1000


def parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def display_time(value: Any) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return str(value or "-")
    return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def safe_file_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "benchmark"


def transcription_rows(result: dict[str, Any]) -> list[str]:
    formatted = result.get("formattedTranscript")
    if isinstance(formatted, str) and formatted.strip():
        return formatted.strip().splitlines()
    rows: list[str] = []
    for segment in result.get("transcriptSegments") or []:
        if not isinstance(segment, dict):
            continue
        start = number(segment.get("fromMs")) or 0
        end = number(segment.get("toMs")) or 0
        text = str(segment.get("text") or "").strip()
        if text:
            rows.append(f"[{start / 1000:.3f},{end / 1000:.3f}]\tPRED\tunknown\t{text}")
    return rows


def repeated_rows(result: dict[str, Any]) -> list[tuple[str, int]]:
    texts = [
        str(item.get("text") or "").strip()
        for item in result.get("transcriptSegments") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return [(text, count) for text, count in Counter(texts).most_common() if count >= 3]


def report(data: dict[str, Any], source: Path) -> tuple[str, dict[str, Any]]:
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    samples = data.get("samples") if isinstance(data.get("samples"), list) else []
    audio_ms = number(result.get("audioDurationMs"))
    processing_ms = number(result.get("processingTimeMs"))
    rtf = processing_ms / audio_ms if processing_ms is not None and audio_ms else None
    speed = audio_ms / processing_ms if processing_ms else None
    cores = number(device.get("logicalCpuCores"))
    average_cpu = number(summary.get("averageCpuPercent"))
    normalized_cpu = average_cpu / cores if average_cpu is not None and cores else None
    start = parse_time(data.get("startedAt"))
    end = parse_time(data.get("completedAt"))
    elapsed = (end - start).total_seconds() if start is not None and end is not None else None
    screen_off = sum(
        1 for sample in samples if isinstance(sample, dict) and sample.get("screenInteractive") is False
    )
    rows = transcription_rows(result)
    repeats = repeated_rows(result)
    status = str(data.get("status") or "unknown")
    title = f"{data.get('modelId') or 'unknown-model'} · STT 벤치마크 결과"

    lines = [
        f"# {title}",
        "",
        "## 실행 정보",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 실행 ID | `{data.get('runId') or '-'}` |",
        f"| 상태 | `{status}` |",
        f"| 시작 | {display_time(data.get('startedAt'))} |",
        f"| 완료 | {display_time(data.get('completedAt'))} |",
        f"| 전체 경과 시간 | {fmt(elapsed, 2, '초')} |",
        f"| 오디오 | `{data.get('sampleAssetPath') or '-'}` |",
        f"| 모델 | `{data.get('modelId') or '-'}` |",
        f"| CPU threads | {data.get('threads', '-')} |",
        "",
        "## 기기",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 제조사 | {device.get('manufacturer') or '-'} |",
        f"| 모델 | {device.get('model') or '-'} |",
        f"| 운영체제 | {device.get('osVersion') or '-'} |",
        f"| 논리 CPU 코어 | {device.get('logicalCpuCores', '-')} |",
        f"| 전체 RAM | {fmt(number(device.get('totalMemoryBytes')) / 1_000_000_000 if number(device.get('totalMemoryBytes')) is not None else None, 2, 'GB')} |",
        "",
        "## 성능 요약",
        "",
        "| 지표 | 값 |",
        "|---|---:|",
        f"| 오디오 길이 | {fmt(duration_seconds(result.get('audioDurationMs')), 2, '초')} |",
        f"| 처리시간 | {fmt(duration_seconds(result.get('processingTimeMs')), 2, '초')} |",
        f"| Asset staging | {fmt(duration_seconds(result.get('stagingTimeMs')), 3, '초')} |",
        f"| RTF | {fmt(rtf, 3)} |",
        f"| 실시간 대비 속도 | {fmt(speed, 2, 'x')} |",
        f"| Segment 수 | {result.get('segments', '-')} |",
        f"| 평균 CPU (코어 환산) | {fmt(average_cpu, 1, '%')} |",
        f"| 평균 CPU (기기 정규화) | {fmt(normalized_cpu, 1, '%')} |",
        f"| Peak CPU | {fmt(number(summary.get('peakCpuPercent')), 1, '%')} |",
        f"| 평균 PSS RAM | {fmt(number(summary.get('averageMemoryMb')), 1, 'MB')} |",
        f"| Peak PSS RAM | {fmt(number(summary.get('peakMemoryMb')), 1, 'MB')} |",
        f"| 최고 발열 상태 | `{summary.get('maximumThermalStatus') or '-'}` |",
        f"| 최고 thermal headroom | {fmt(number(summary.get('maximumThermalHeadroom')), 3)} |",
        f"| 최고 배터리 온도 | {fmt(number(summary.get('maximumBatteryTemperatureC')), 1, '°C')} |",
        f"| Telemetry sample | {len(samples)}개 |",
        f"| 화면 꺼짐 sample | {screen_off}개 |",
    ]
    error = data.get("error")
    if error:
        lines += ["", "## 오류", "", f"> {str(error).replace(chr(10), ' ')}"]
    if repeats:
        lines += ["", "## 반복 출력 확인", "", "| 반복 횟수 | 문장 |", "|---:|---|"]
        for text, count in repeats:
            escaped_text = text.replace("|", "\\|")
            lines.append(f"| {count} | {escaped_text} |")
    lines += [
        "",
        "## STT 출력",
        "",
        "KCSC TXT와 동일한 `시간 → 화자 → 성별 → 문장` 4열 형식입니다.",
        "",
        "```text",
        *(rows or ["(출력 없음)"]),
        "```",
        "",
        f"원본 JSON: `{source}`",
        "",
    ]
    index_row = {
        "started": display_time(data.get("startedAt")),
        "model": str(data.get("modelId") or "-"),
        "status": status,
        "processing": fmt(duration_seconds(result.get("processingTimeMs")), 2, "초"),
        "rtf": fmt(rtf, 3),
        "ram": fmt(number(summary.get("peakMemoryMb")), 1, "MB"),
    }
    return "\n".join(lines), index_row


def discover(path: Path) -> list[Path]:
    return [path] if path.is_file() else sorted(path.rglob("*.json"), key=lambda item: (len(item.parts), str(item)))


def main() -> None:
    args = parse_args()
    source_root = args.input.expanduser().resolve()
    output = (args.output or (source_root if source_root.is_dir() else source_root.parent) / "markdown").expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    unique: dict[str, tuple[dict[str, Any], Path]] = {}
    duplicate_count = 0
    for source in discover(source_root):
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        run_id = str(data.get("runId") or source.stem)
        if run_id in unique:
            duplicate_count += 1
            continue
        unique[run_id] = (data, source)

    index_rows: list[tuple[str, dict[str, Any]]] = []
    for run_id, (data, source) in sorted(
        unique.items(), key=lambda item: str(item[1][0].get("startedAt") or "")
    ):
        model = safe_file_name(str(data.get("modelId") or "unknown-model"))
        started = parse_time(data.get("startedAt"))
        stamp = started.astimezone(KST).strftime("%Y%m%dT%H%M%S") if started else safe_file_name(run_id)
        name = f"{stamp}_{model}.md"
        content, index_row = report(data, source)
        (output / name).write_text(content, encoding="utf-8")
        index_rows.append((name, index_row))

    index = [
        "# STT 벤치마크 결과 목록",
        "",
        f"고유 실행 {len(index_rows)}개를 변환했습니다. 중복 JSON {duplicate_count}개는 제외했습니다.",
        "",
        "| 실행 시각 | 모델 | 상태 | 처리시간 | RTF | Peak RAM | 보고서 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for name, row in reversed(index_rows):
        index.append(
            f"| {row['started']} | `{row['model']}` | `{row['status']}` | "
            f"{row['processing']} | {row['rtf']} | {row['ram']} | [{name}]({name}) |"
        )
    index.append("")
    (output / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    print(f"변환 완료: {len(index_rows)}개 → {output}")
    if duplicate_count:
        print(f"중복 제외: {duplicate_count}개")


if __name__ == "__main__":
    main()
