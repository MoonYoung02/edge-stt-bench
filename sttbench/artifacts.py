"""Standardized, engine-independent inspection artifacts."""

from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import numpy as np

from sttbench.adapters.base import AdapterResult
from sttbench.datasets.kcsc import ReferenceSegment
from sttbench.metrics.text import compare
from sttbench.schema import Transcript


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"JSON으로 저장할 수 없습니다: {type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_artifacts(
    sample_dir: Path,
    audio_path: Path,
    result: AdapterResult,
    references: list[ReferenceSegment] | None,
) -> tuple[dict | None, list[str]]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = sample_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    transcript = result.transcript

    np.save(sample_dir / "audio_16k_mono.npy", result.audio)
    np.save(sample_dir / "log_mel_spectrogram.npy", result.mel)
    write_json(
        sample_dir / "log_mel_summary.json",
        {
            "shape": list(result.mel.shape),
            "dtype": str(result.mel.dtype),
            "min": float(result.mel.min()),
            "max": float(result.mel.max()),
            "mean": float(result.mel.mean()),
            "std": float(result.mel.std()),
        },
    )
    write_json(sample_dir / "transcript.json", transcript.to_dict())
    write_json(raw_dir / "result.json", result.raw_result)
    (raw_dir / "engine.log").write_text(result.log, encoding="utf-8")

    save_transcript_files(sample_dir, transcript)
    save_tables(sample_dir, transcript)
    save_predicted_labeled(sample_dir / "transcript_labeled.txt", transcript)
    if result.language_probabilities:
        write_csv(
            sample_dir / "language_probabilities.csv",
            ["language", "probability"],
            [
                {"language": language, "probability": probability}
                for language, probability in sorted(
                    result.language_probabilities.items(), key=lambda item: -item[1]
                )
            ],
        )

    warnings: list[str] = []
    info = audio_info(audio_path)
    write_json(sample_dir / "input_info.json", info)
    warnings.extend(save_audio_images(audio_path, sample_dir))

    comparison: dict | None = None
    if references is not None:
        reference_text = " ".join(segment.text for segment in references)
        comparison = compare(reference_text, transcript.text)
        comparison["reference_segments"] = len(references)
        write_json(sample_dir / "comparison.json", comparison)
        write_json(sample_dir / "reference.json", [segment.to_dict() for segment in references])
        (sample_dir / "reference.txt").write_text(reference_text + "\n", encoding="utf-8")
        save_reference_labeled(sample_dir / "reference_labeled.txt", references)
        write_csv(
            sample_dir / "reference_segments.csv",
            ["start", "end", "speaker", "gender", "text"],
            [asdict(segment) for segment in references],
        )

    save_file_index(sample_dir)
    return comparison, warnings


def save_transcript_files(output_dir: Path, transcript: Transcript) -> None:
    (output_dir / "transcript.txt").write_text(transcript.text + "\n", encoding="utf-8")
    srt_lines: list[str] = []
    vtt_lines = ["WEBVTT", ""]
    tsv_rows: list[dict] = []
    for index, segment in enumerate(transcript.segments, start=1):
        srt_lines.extend(
            [
                str(index),
                f"{timestamp(segment.start, srt=True)} --> {timestamp(segment.end, srt=True)}",
                segment.text,
                "",
            ]
        )
        vtt_lines.extend(
            [
                f"{timestamp(segment.start)} --> {timestamp(segment.end)}",
                segment.text,
                "",
            ]
        )
        tsv_rows.append({"start": segment.start, "end": segment.end, "text": segment.text})
    (output_dir / "transcript.srt").write_text("\n".join(srt_lines), encoding="utf-8")
    (output_dir / "transcript.vtt").write_text("\n".join(vtt_lines), encoding="utf-8")
    write_csv(output_dir / "transcript.tsv", ["start", "end", "text"], tsv_rows)


def save_tables(output_dir: Path, transcript: Transcript) -> None:
    segment_rows: list[dict] = []
    word_rows: list[dict] = []
    token_rows: list[dict] = []
    for segment in transcript.segments:
        segment_rows.append(
            {
                "segment_id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "speaker": segment.speaker,
                "text": segment.text,
                "confidence": segment.confidence,
                "word_count": len(segment.words),
                "token_count": len(segment.tokens),
                **segment.metadata,
            }
        )
        for index, word in enumerate(segment.words):
            word_rows.append(
                {
                    "segment_id": segment.id,
                    "word_index": index,
                    "start": word.start,
                    "end": word.end,
                    "word": word.text,
                    "confidence": word.confidence,
                }
            )
        for index, token in enumerate(segment.tokens):
            token_rows.append(
                {
                    "segment_id": segment.id,
                    "token_index": index,
                    "token_id": token.id,
                    "decoded": token.text,
                    "start": token.start,
                    "end": token.end,
                    "confidence": token.confidence,
                }
            )
    segment_fields = ["segment_id", "start", "end", "speaker", "text", "confidence", "word_count", "token_count"]
    extra_fields = sorted({key for row in segment_rows for key in row if key not in segment_fields})
    write_csv(output_dir / "segments.csv", segment_fields + extra_fields, segment_rows)
    write_csv(
        output_dir / "words.csv",
        ["segment_id", "word_index", "start", "end", "word", "confidence"],
        word_rows,
    )
    write_csv(
        output_dir / "tokens.csv",
        ["segment_id", "token_index", "token_id", "decoded", "start", "end", "confidence"],
        token_rows,
    )


def save_predicted_labeled(path: Path, transcript: Transcript) -> None:
    lines = [
        f"[{segment.start:.3f},{segment.end:.3f}]\t{segment.speaker or 'unknown'}\tunknown\t{segment.text}"
        for segment in transcript.segments
        if segment.text
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def save_reference_labeled(path: Path, references: list[ReferenceSegment]) -> None:
    lines = [
        f"[{segment.start:.3f},{segment.end:.3f}]\t{segment.speaker}\t{segment.gender}\t{segment.text}"
        for segment in references
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def timestamp(seconds: float, *, srt: bool = False) -> str:
    milliseconds = round(max(0, seconds) * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def audio_info(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {"input": str(path), "warning": "ffprobe 없음"}
    process = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        return {"input": str(path), "warning": process.stderr.strip()}
    payload = json.loads(process.stdout)
    payload["input"] = str(path)
    return payload


def save_audio_images(audio_path: Path, output_dir: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return ["ffmpeg가 없어 파형과 스펙트로그램을 만들지 못했습니다."]
    filters = [
        ("waveform.png", "showwavespic=s=1600x360:colors=0x2F80ED"),
        ("audio_spectrogram.png", "showspectrumpic=s=1600x800:legend=1:color=intensity"),
    ]
    warnings: list[str] = []
    for filename, audio_filter in filters:
        process = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(audio_path),
                "-lavfi",
                audio_filter,
                "-frames:v",
                "1",
                str(output_dir / filename),
            ],
            capture_output=True,
            text=True,
        )
        if process.returncode:
            warnings.append(f"{filename} 생성 실패: {process.stderr.strip()}")
    return warnings


def save_file_index(output_dir: Path) -> None:
    descriptions = {
        "transcript.json": "모든 모델에 공통인 정규화 전사 결과",
        "transcript.txt": "최종 전체 전사문",
        "transcript_labeled.txt": "모델이 예측한 구간/화자(미지원 모델은 unknown)",
        "reference_labeled.txt": "데이터셋 정답의 구간/화자/성별/텍스트",
        "reference.json": "모델 결과와 분리된 데이터셋 정답",
        "comparison.json": "정답이 있을 때 전체 CER/WER",
        "segments.csv": "공통 구간 출력",
        "words.csv": "공통 단어 출력",
        "tokens.csv": "공통 토큰 출력",
        "raw": "엔진 원본 출력과 실행 로그",
        "audio_16k_mono.npy": "모델 입력 16kHz 모노 배열",
        "log_mel_spectrogram.npy": "Whisper log-Mel 배열",
        "input_info.json": "원본 오디오 코덱과 스트림 정보",
        "diarization.json": "겹침을 포함한 pyannote 화자 구간",
        "exclusive_diarization.json": "STT 정렬용 단일 화자 구간",
        "diarization.rttm": "표준 RTTM 화자 분리 결과",
        "overlap_segments.json": "두 명 이상이 동시에 말한 구간",
        "speaker_transcript.json": "단어 타임스탬프와 화자를 결합한 결과",
        "speaker_transcript.txt": "[시작,종료] 화자 성별 전사문 형식의 결합 결과",
    }
    lines = ["생성된 STT 산출물", ""]
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        lines.append(f"{path.name}: {descriptions.get(path.name, '추가 산출물')}")
    (output_dir / "FILES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
