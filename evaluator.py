from __future__ import annotations

import csv
import json
import random
import re
import shutil
import subprocess
import time
import unicodedata
import wave
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Sequence, TypeVar

import numpy as np
import torch
import whisper
from tqdm import tqdm
from whisper.audio import N_FRAMES
from whisper.tokenizer import get_tokenizer
from whisper.utils import get_writer


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "kcsc"
RESULTS_DIR = ROOT / "results"
PREDICTIONS_PATH = RESULTS_DIR / "predictions.csv"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
MODEL = "large-v3-turbo"
MODEL_PATH = Path.home() / ".cache" / "whisper" / f"{MODEL}.pt"
BUCKET = "hf://buckets/happy7656/korean-conversational-speech-corpus-bucket"
SAMPLE_RATE = 16_000
TEST_SIZE = 10
TEST_SEED = 7656
CPP_MODEL_NAME = "whisper-base-q5_1"
CPP_MODEL_PATH = ROOT / "models" / "ggml-base-q5_1.bin"
INSPECT_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    CPP_MODEL_NAME,
)
INSPECT_TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
INSPECT_COMPRESSION_RATIO_THRESHOLD = 2.4
INSPECT_LOGPROB_THRESHOLD = -1.0
INSPECT_NO_SPEECH_THRESHOLD = 0.6
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
CPP_NATIVE_AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg"}

LINE_RE = re.compile(
    r"^\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]"
    r"\s+(\S+)\s+(\S+)\s+(.*?)\s*$"
)
TAG_RE = re.compile(r"\[(?:LAUGHTER|SONANT|MUSIC|SYSTEM|ENS)\]", re.IGNORECASE)
UNKNOWN_RE = re.compile(r"\[\*\]")

CSV_FIELDS = [
    "sample_id",
    "status",
    "wav",
    "start",
    "end",
    "duration",
    "reference",
    "prediction",
    "char_errors",
    "ref_chars",
    "word_errors",
    "ref_words",
    "seconds",
    "error",
]


@dataclass(frozen=True)
class Sample:
    sample_id: str
    wav: Path
    start: float
    end: float
    reference: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise UnicodeError(f"텍스트 인코딩을 읽을 수 없습니다: {path}")


def normalize_words(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = TAG_RE.sub(" ", text)
    text = UNKNOWN_RE.sub(" ", text)
    text = "".join(char if (char.isalnum() or char.isspace()) else " " for char in text)
    return " ".join(text.split())


def normalize_chars(text: str) -> str:
    return "".join(normalize_words(text).split())


T = TypeVar("T")


def edit_distance(reference: Sequence[T], prediction: Sequence[T]) -> int:
    if len(reference) < len(prediction):
        reference, prediction = prediction, reference
    previous = list(range(len(prediction) + 1))
    for ref_index, ref_item in enumerate(reference, 1):
        current = [ref_index]
        for pred_index, pred_item in enumerate(prediction, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[pred_index] + 1,
                    previous[pred_index - 1] + (ref_item != pred_item),
                )
            )
        previous = current
    return previous[-1]


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"JSON으로 저장할 수 없습니다: {type(value).__name__}")


def write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sanitize_utf8_file(path: Path) -> None:
    text = path.read_bytes().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")


def format_elapsed(seconds: float) -> str:
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}시간 {minutes}분 {remainder:.2f}초"
    if minutes:
        return f"{minutes}분 {remainder:.2f}초"
    return f"{seconds:.2f}초"


def probe_audio_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    process = subprocess.run(
        [
            ffprobe,
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
    if process.returncode != 0:
        return None
    try:
        return float(process.stdout.strip())
    except ValueError:
        return None


def runtime_estimate(model_name: str, audio_seconds: float | None) -> dict:
    estimate = {
        "audio_seconds": audio_seconds,
        "estimated_total_seconds": None,
        "basis": None,
    }
    if audio_seconds is None:
        return estimate

    history: list[tuple[float, Path, dict]] = []
    for summary_path in (RESULTS_DIR / "inspect").glob("*/run_summary.json"):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if summary.get("model") != model_name or not summary.get("audio_seconds"):
            continue
        history.append((summary_path.stat().st_mtime, summary_path, summary))

    if not history:
        return estimate

    _mtime, summary_path, summary = max(history, key=lambda item: item[0])
    previous_audio_seconds = float(summary["audio_seconds"])
    inference_seconds = summary.get("transcribe_seconds")
    if inference_seconds is None:
        inference_seconds = summary.get("model_load_and_transcribe_seconds")
    total_seconds = summary.get("total_seconds")
    if inference_seconds is None or total_seconds is None:
        return estimate

    inference_seconds = float(inference_seconds)
    fixed_overhead = max(0.0, float(total_seconds) - inference_seconds)
    estimated_total = fixed_overhead + (inference_seconds / previous_audio_seconds) * audio_seconds
    estimate.update(
        {
            "estimated_total_seconds": estimated_total,
            "basis": str(summary_path),
            "basis_audio_seconds": previous_audio_seconds,
            "basis_total_seconds": float(total_seconds),
        }
    )
    return estimate


def show_runtime_estimate(path: Path, model_name: str) -> dict:
    estimate = runtime_estimate(model_name, probe_audio_duration(path))
    if estimate["audio_seconds"] is None:
        print("음성 길이: 확인할 수 없음")
    else:
        print(f"음성 길이: {format_elapsed(estimate['audio_seconds'])}")
    if estimate["estimated_total_seconds"] is None:
        print("예상 전체 실행 시간: 이전 동일 모델 기록 없음 (진행 후 ETA 계산)")
    else:
        print(
            "예상 전체 실행 시간: 약 "
            f"{format_elapsed(estimate['estimated_total_seconds'])} "
            "(최근 동일 모델 기록 기준)"
        )
    return estimate


def run_cpp_with_progress(command: list[str]) -> tuple[int, str, float]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = bytearray()
    last_progress = -1
    try:
        assert process.stdout is not None
        for raw_line in iter(process.stdout.readline, b""):
            output.extend(raw_line)
            line = raw_line.decode("utf-8", errors="replace")
            match = re.search(r"progress\s*=\s*(\d+)%", line)
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
        print(
            f"\rSTT 진행: 100% | 경과 {format_elapsed(elapsed)} | 남은 시간 약 0.00초",
            end="",
            flush=True,
        )
    if last_progress >= 0 or returncode == 0:
        print()
    return returncode, output.decode("utf-8", errors="replace"), elapsed


def discover_samples() -> list[Sample]:
    txt_dir = DATA_DIR / "TXT"
    wav_dir = DATA_DIR / "WAV"
    if not txt_dir.is_dir() or not wav_dir.is_dir():
        raise FileNotFoundError("데이터가 없습니다. 먼저 'python cli.py download'를 실행하세요.")

    wavs = {path.stem.casefold(): path for path in wav_dir.rglob("*.wav")}
    samples: list[Sample] = []
    for txt_path in sorted(txt_dir.rglob("*.txt")):
        wav_path = wavs.get(txt_path.stem.casefold())
        if wav_path is None:
            continue
        for line_number, line in enumerate(decode_text(txt_path).splitlines(), 1):
            match = LINE_RE.match(line.strip())
            if not match:
                continue
            start_text, end_text, _speaker, _gender, reference = match.groups()
            start, end = float(start_text), float(end_text)
            if end <= start or UNKNOWN_RE.search(reference) or not normalize_chars(reference):
                continue
            relative_wav = wav_path.relative_to(DATA_DIR).as_posix()
            sample_id = f"{relative_wav}|{start:.3f}|{end:.3f}|{line_number}"
            samples.append(Sample(sample_id, wav_path, start, end, reference.strip()))
    return samples


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        width = wav_file.getsampwidth()
        rate = wav_file.getframerate()
        compressed = wav_file.getcomptype()
        raw = wav_file.readframes(wav_file.getnframes())
    if width != 2 or rate != SAMPLE_RATE or compressed != "NONE":
        raise ValueError(f"16kHz 16-bit PCM WAV가 아닙니다: {path.name}")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(audio, dtype=np.float32)


def ensure_mps() -> None:
    if not hasattr(torch.backends, "mps") or not torch.backends.mps.is_available():
        raise RuntimeError("이 Mac에서 MPS를 사용할 수 없습니다.")


def check() -> int:
    mps_ready = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    txt_count = len(list((DATA_DIR / "TXT").glob("*.txt"))) if DATA_DIR.exists() else 0
    wav_count = len(list((DATA_DIR / "WAV").glob("*.wav"))) if DATA_DIR.exists() else 0
    model_ready = MODEL_PATH.exists()
    cpp_ready = shutil.which("whisper-cli") is not None and CPP_MODEL_PATH.exists()

    print(f"M4 GPU: {'준비됨' if mps_ready else '사용 불가'}")
    print(f"Whisper 모델: {'준비됨' if model_ready else '첫 실행 때 다운로드'}")
    print(f"Whisper.cpp Q5_1: {'준비됨' if cpp_ready else '설치되지 않음'}")
    print(f"평가 데이터: TXT {txt_count}개 / WAV {wav_count}개")
    ready = mps_ready and txt_count > 0 and wav_count > 0
    print("상태: " + ("평가 준비 완료" if ready else "준비가 더 필요합니다"))
    return 0 if ready else 1


def download() -> None:
    try:
        from huggingface_hub import sync_bucket
    except ImportError as exc:
        raise RuntimeError("huggingface_hub가 설치되지 않았습니다.") from exc

    print("정답 텍스트를 확인하고 있습니다...")
    sync_bucket(f"{BUCKET}/TXT", str(DATA_DIR / "TXT"))
    print("음성 파일을 확인하고 있습니다...")
    sync_bucket(f"{BUCKET}/WAV", str(DATA_DIR / "WAV"))
    print("데이터 준비 완료")


def resolve_audio(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {path}")
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(AUDIO_EXTENSIONS))
        raise ValueError(f"지원하지 않는 오디오 형식입니다: {path.suffix} (지원: {supported})")
    return path


def inspect_output_dir(wav_path: Path, model_name: str) -> Path:
    normalized_stem = unicodedata.normalize("NFC", wav_path.stem)
    safe_stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", normalized_stem)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = RESULTS_DIR / "inspect" / f"{safe_stem}__{model_name}__{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def save_audio_info(wav_path: Path, output_dir: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        process = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(wav_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        info = json.loads(process.stdout)
    else:
        with wave.open(str(wav_path), "rb") as wav_file:
            info = {
                "channels": wav_file.getnchannels(),
                "sample_width_bytes": wav_file.getsampwidth(),
                "sample_rate": wav_file.getframerate(),
                "frames": wav_file.getnframes(),
                "compression": wav_file.getcomptype(),
            }
    write_json(output_dir / "input_info.json", info)
    return info


def save_audio_images(wav_path: Path, output_dir: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ["ffmpeg가 없어 waveform.png와 audio_spectrogram.png를 만들지 못했습니다."]
    commands = [
        (
            output_dir / "waveform.png",
            "aformat=channel_layouts=mono,showwavespic=s=1600x400:colors=0x35A7FF",
        ),
        (
            output_dir / "audio_spectrogram.png",
            "showspectrumpic=s=1600x900:legend=1:scale=log:color=viridis",
        ),
    ]
    warnings: list[str] = []
    for target, audio_filter in commands:
        process = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-lavfi",
                audio_filter,
                "-frames:v",
                "1",
                str(target),
            ],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            warnings.append(f"{target.name} 생성 실패: {process.stderr.strip()}")
    return warnings


def save_standard_transcripts(result: dict, wav_path: Path, output_dir: Path) -> None:
    for output_format in ("txt", "srt", "vtt", "tsv"):
        get_writer(output_format, str(output_dir))(result, str(wav_path))
        generated = output_dir / f"{wav_path.stem}.{output_format}"
        target = output_dir / f"transcript.{output_format}"
        if generated != target:
            generated.replace(target)


def save_result_tables(result: dict, model, output_dir: Path) -> None:
    segment_rows: list[dict] = []
    word_rows: list[dict] = []
    token_rows: list[dict] = []
    tokenizer = get_tokenizer(
        model.is_multilingual,
        language=result.get("language"),
        task="transcribe",
        num_languages=model.num_languages,
    )
    for segment in result.get("segments", []):
        segment_id = segment.get("id")
        tokens = segment.get("tokens", [])
        segment_rows.append(
            {
                "segment_id": segment_id,
                "seek": segment.get("seek"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text", "").strip(),
                "temperature": segment.get("temperature"),
                "avg_logprob": segment.get("avg_logprob"),
                "compression_ratio": segment.get("compression_ratio"),
                "no_speech_prob": segment.get("no_speech_prob"),
                "token_count": len(tokens),
            }
        )
        for word_index, word in enumerate(segment.get("words", [])):
            word_rows.append(
                {
                    "segment_id": segment_id,
                    "word_index": word_index,
                    "start": word.get("start"),
                    "end": word.get("end"),
                    "word": word.get("word", ""),
                    "probability": word.get("probability"),
                }
            )
        for token_index, token_id in enumerate(tokens):
            token_rows.append(
                {
                    "segment_id": segment_id,
                    "token_index": token_index,
                    "token_id": token_id,
                    "decoded": tokenizer.decode([token_id]),
                }
            )

    write_csv(
        output_dir / "segments.csv",
        [
            "segment_id",
            "seek",
            "start",
            "end",
            "text",
            "temperature",
            "avg_logprob",
            "compression_ratio",
            "no_speech_prob",
            "token_count",
        ],
        segment_rows,
    )
    write_csv(
        output_dir / "words.csv",
        ["segment_id", "word_index", "start", "end", "word", "probability"],
        word_rows,
    )
    write_csv(
        output_dir / "tokens.csv",
        ["segment_id", "token_index", "token_id", "decoded"],
        token_rows,
    )


def cpp_result(raw_result: dict) -> dict:
    segments: list[dict] = []
    texts: list[str] = []
    for segment_id, item in enumerate(raw_result.get("transcription", [])):
        offsets = item.get("offsets", {})
        text = item.get("text", "").strip()
        if text:
            texts.append(text)
        segments.append(
            {
                "id": segment_id,
                "start": float(offsets.get("from", 0)) / 1000,
                "end": float(offsets.get("to", 0)) / 1000,
                "text": text,
                "tokens": item.get("tokens", []),
            }
        )
    return {
        "text": " ".join(texts),
        "language": raw_result.get("result", {}).get("language", "ko"),
        "segments": segments,
    }


def save_cpp_result_tables(result: dict, output_dir: Path) -> tuple[int, int]:
    segment_rows: list[dict] = []
    word_rows: list[dict] = []
    token_rows: list[dict] = []

    for segment in result.get("segments", []):
        segment_id = segment["id"]
        tokens = segment.get("tokens", [])
        segment_rows.append(
            {
                "segment_id": segment_id,
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
                "token_count": len(tokens),
            }
        )

        word: dict | None = None
        for token_index, token in enumerate(tokens):
            piece = token.get("text", "")
            offsets = token.get("offsets", {})
            start = float(offsets.get("from", 0)) / 1000
            end = float(offsets.get("to", 0)) / 1000
            probability = token.get("p")
            token_rows.append(
                {
                    "segment_id": segment_id,
                    "token_index": token_index,
                    "token_id": token.get("id"),
                    "decoded": piece,
                    "start": start,
                    "end": end,
                    "probability": probability,
                }
            )

            if piece.startswith("[") and piece.endswith("]"):
                continue
            if piece.startswith(" ") and word is not None:
                word_rows.append(word)
                word = None
            if word is None:
                word = {
                    "segment_id": segment_id,
                    "word_index": len([r for r in word_rows if r["segment_id"] == segment_id]),
                    "start": start,
                    "end": end,
                    "word": piece.strip(),
                    "probabilities": [probability] if probability is not None else [],
                }
            else:
                word["end"] = max(word["end"], end)
                word["word"] += piece
                if probability is not None:
                    word["probabilities"].append(probability)
        if word is not None:
            word_rows.append(word)

    for row in word_rows:
        probabilities = row.pop("probabilities")
        row["probability"] = sum(probabilities) / len(probabilities) if probabilities else None

    write_csv(
        output_dir / "segments.csv",
        ["segment_id", "start", "end", "text", "token_count"],
        segment_rows,
    )
    write_csv(
        output_dir / "words.csv",
        ["segment_id", "word_index", "start", "end", "word", "probability"],
        word_rows,
    )
    write_csv(
        output_dir / "tokens.csv",
        ["segment_id", "token_index", "token_id", "decoded", "start", "end", "probability"],
        token_rows,
    )
    write_csv(
        output_dir / "transcript.tsv",
        ["start", "end", "text"],
        [
            {"start": row["start"], "end": row["end"], "text": row["text"]}
            for row in segment_rows
        ],
    )
    return len(word_rows), len(token_rows)


def load_speaker_timeline(wav_path: Path) -> list[tuple[float, float, str, str]]:
    reference_path = DATA_DIR / "TXT" / f"{wav_path.stem}.txt"
    if not reference_path.exists():
        return []

    timeline: list[tuple[float, float, str, str]] = []
    for line in decode_text(reference_path).splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        start, end, speaker, gender, _text = match.groups()
        timeline.append((float(start), float(end), speaker, gender))
    return timeline


def segment_speaker(
    start: float,
    end: float,
    timeline: list[tuple[float, float, str, str]],
) -> tuple[str, str]:
    if not timeline:
        return "unknown", "unknown"

    def overlap(item: tuple[float, float, str, str]) -> float:
        ref_start, ref_end, _speaker, _gender = item
        return max(0.0, min(end, ref_end) - max(start, ref_start))

    best = max(timeline, key=overlap)
    if overlap(best) > 0:
        return best[2], best[3]

    midpoint = (start + end) / 2
    nearest = min(
        timeline,
        key=lambda item: min(abs(midpoint - item[0]), abs(midpoint - item[1])),
    )
    return nearest[2], nearest[3]


def save_labeled_transcript(result: dict, wav_path: Path, output_dir: Path) -> Path:
    timeline = load_speaker_timeline(wav_path)
    lines: list[str] = []
    for segment in result.get("segments", []):
        text = " ".join(segment.get("text", "").split())
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        speaker, gender = segment_speaker(start, end, timeline)
        lines.append(f"[{start:.3f},{end:.3f}]\t{speaker}\t{gender}\t{text}")

    target = output_dir / "transcript_labeled.txt"
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def save_reference_comparison(wav_path: Path, prediction: str, output_dir: Path) -> dict | None:
    reference_path = DATA_DIR / "TXT" / f"{wav_path.stem}.txt"
    if not reference_path.exists():
        return None
    rows: list[dict] = []
    texts: list[str] = []
    for line_number, line in enumerate(decode_text(reference_path).splitlines(), 1):
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        start, end, speaker, gender, text = match.groups()
        if UNKNOWN_RE.search(text) or not normalize_chars(text):
            continue
        rows.append(
            {
                "line": line_number,
                "start": start,
                "end": end,
                "speaker": speaker,
                "gender": gender,
                "text": text,
            }
        )
        texts.append(text)

    reference = " ".join(texts)
    ref_chars = normalize_chars(reference)
    pred_chars = normalize_chars(prediction)
    ref_words = normalize_words(reference).split()
    pred_words = normalize_words(prediction).split()
    comparison = {
        "reference_file": str(reference_path),
        "reference_segments": len(rows),
        "cer": edit_distance(ref_chars, pred_chars) / len(ref_chars) if ref_chars else None,
        "wer": edit_distance(ref_words, pred_words) / len(ref_words) if ref_words else None,
    }
    (output_dir / "reference.txt").write_text(reference + "\n", encoding="utf-8")
    write_csv(
        output_dir / "reference_segments.csv",
        ["line", "start", "end", "speaker", "gender", "text"],
        rows,
    )
    write_json(output_dir / "comparison.json", comparison)
    return comparison


def save_file_index(output_dir: Path) -> None:
    descriptions = {
        "FILES.txt": "이 파일: 산출물 설명",
        "run_summary.json": "모델, 장치, 언어, 실행시간 등 실행 요약",
        "input_info.json": "원본 WAV의 코덱, 채널, 샘플레이트 정보",
        "waveform.png": "원본 음성 파형",
        "audio_spectrogram.png": "원본 음성의 주파수 스펙트로그램",
        "audio_16k_mono.npy": "Whisper에 전달된 16kHz 모노 float32 배열",
        "log_mel_spectrogram.npy": "Whisper 인코더 입력 log-Mel 배열",
        "log_mel_summary.json": "log-Mel 배열의 크기와 통계",
        "language_probabilities.csv": "모델이 계산한 모든 언어 확률",
        "result.json": "Whisper가 반환한 원본 전체 결과",
        "transcript.txt": "최종 전사문",
        "transcript_labeled.txt": "[시작,종료] 화자 성별 전사문 형식의 전체 결과",
        "transcript.srt": "SRT 자막",
        "transcript.vtt": "WebVTT 자막",
        "transcript.tsv": "구간 시간과 전사문",
        "segments.csv": "구간별 텍스트와 로그확률·무음확률 등",
        "words.csv": "단어별 시작/종료 시간과 확률",
        "tokens.csv": "구간별 토큰 ID와 디코딩 문자열",
        "reference.txt": "같은 이름의 데이터셋 정답을 합친 텍스트",
        "reference_segments.csv": "정답 타임스탬프 구간",
        "comparison.json": "정답이 있을 때 전체 CER/WER",
        "whisper_cpp.log": "whisper.cpp 실행 명령과 원본 로그",
        "whisper_cpp_segments.csv": "whisper.cpp가 직접 생성한 원본 구간 CSV",
        "converted_input_16k.wav": "whisper.cpp 입력용으로 자동 변환한 16kHz 모노 WAV",
    }
    lines = ["생성된 STT 산출물", ""]
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        lines.append(f"{path.name}: {descriptions.get(path.name, '추가 산출물')}")
    (output_dir / "FILES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def inspect_wav_cpp(wav_path: Path, model_name: str) -> None:
    overall_started = time.perf_counter()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    wav_path = resolve_audio(wav_path)
    executable = shutil.which("whisper-cli")
    if executable is None:
        raise RuntimeError("whisper-cli가 없습니다. 'brew install whisper-cpp'를 실행하세요.")
    if not CPP_MODEL_PATH.is_file():
        raise FileNotFoundError(f"Q5_1 모델 파일이 없습니다: {CPP_MODEL_PATH}")

    output_dir = inspect_output_dir(wav_path, model_name)
    print(f"입력: {wav_path}")
    print(f"모델: {model_name}")
    print("엔진: whisper.cpp / Metal")
    estimate = show_runtime_estimate(wav_path, model_name)

    print("Whisper 입력을 저장하는 중...")
    preprocess_started = time.perf_counter()
    audio = whisper.load_audio(str(wav_path))
    mel = whisper.log_mel_spectrogram(audio, n_mels=80)
    np.save(output_dir / "audio_16k_mono.npy", audio)
    mel_array = mel.cpu().numpy()
    np.save(output_dir / "log_mel_spectrogram.npy", mel_array)
    write_json(
        output_dir / "log_mel_summary.json",
        {
            "shape": list(mel_array.shape),
            "dtype": str(mel_array.dtype),
            "min": float(mel_array.min()),
            "max": float(mel_array.max()),
            "mean": float(mel_array.mean()),
            "std": float(mel_array.std()),
            "note": "whisper.cpp와 동일한 80-bin Whisper log-Mel의 Python 분석용 사본",
        },
    )
    preprocess_seconds = time.perf_counter() - preprocess_started

    cpp_input_path = wav_path
    converted_input = False
    if wav_path.suffix.lower() not in CPP_NATIVE_AUDIO_EXTENSIONS:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("이 오디오 형식을 변환하려면 ffmpeg가 필요합니다.")
        cpp_input_path = output_dir / "converted_input_16k.wav"
        conversion = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(cpp_input_path),
            ],
            capture_output=True,
            text=True,
        )
        if conversion.returncode != 0:
            raise RuntimeError(f"오디오 변환 실패: {conversion.stderr.strip()}")
        converted_input = True
        print(f"whisper.cpp용 WAV 자동 변환: {cpp_input_path.name}")

    print("STT를 실행하는 중...")
    prefix = output_dir / "whisper_cpp"
    command = [
        executable,
        "-m",
        str(CPP_MODEL_PATH),
        "-f",
        str(cpp_input_path),
        "-l",
        "ko",
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
    returncode, process_output, transcribe_seconds = run_cpp_with_progress(command)
    (output_dir / "whisper_cpp.log").write_text(
        "COMMAND\n"
        + " ".join(command)
        + "\n\nOUTPUT\n"
        + process_output,
        encoding="utf-8",
    )
    if returncode != 0:
        raise RuntimeError(f"whisper-cli 실행 실패. 로그: {output_dir / 'whisper_cpp.log'}")

    generated = {
        "json": "result.json",
        "txt": "transcript.txt",
        "srt": "transcript.srt",
        "vtt": "transcript.vtt",
        "csv": "whisper_cpp_segments.csv",
    }
    for extension, target_name in generated.items():
        source = Path(f"{prefix}.{extension}")
        if source.exists():
            target = output_dir / target_name
            source.replace(target)
            sanitize_utf8_file(target)

    raw_result = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    result = cpp_result(raw_result)

    artifacts_started = time.perf_counter()
    words_count, tokens_count = save_cpp_result_tables(result, output_dir)
    labeled_transcript = save_labeled_transcript(result, wav_path, output_dir)
    comparison = save_reference_comparison(wav_path, result["text"], output_dir)
    save_audio_info(wav_path, output_dir)
    warnings = save_audio_images(wav_path, output_dir)
    artifacts_seconds = time.perf_counter() - artifacts_started
    total_seconds = time.perf_counter() - overall_started
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    system_info = raw_result.get("systeminfo", "")
    device = "metal" if "MTL" in system_info else "cpu"
    version_process = subprocess.run(
        [executable, "--version"], capture_output=True, text=True
    )
    version_text = version_process.stdout + "\n" + version_process.stderr
    version_match = re.search(r"whisper\.cpp version:\s*(\S+)", version_text)
    write_json(
        output_dir / "run_summary.json",
        {
            "input": str(wav_path),
            "engine_input": str(cpp_input_path),
            "input_converted_to_wav": converted_input,
            "engine": "whisper.cpp",
            "engine_version": version_match.group(1) if version_match else "unknown",
            "model": model_name,
            "model_file": str(CPP_MODEL_PATH),
            "model_bytes": CPP_MODEL_PATH.stat().st_size,
            "quantization": "Q5_1",
            "device": device,
            "language": result["language"],
            "language_probability": None,
            "decoding": {
                "max_context": 0,
                "temperature": 0.0,
                "temperature_increment": 0.2,
                "entropy_threshold": 2.4,
                "logprob_threshold": -1.0,
                "no_speech_threshold": 0.6,
            },
            "audio_samples": len(audio),
            "audio_seconds": len(audio) / SAMPLE_RATE,
            "runtime_estimate": estimate,
            "started_at": started_at,
            "finished_at": finished_at,
            "preprocess_seconds": preprocess_seconds,
            "model_load_and_transcribe_seconds": transcribe_seconds,
            "artifacts_seconds": artifacts_seconds,
            "total_seconds": total_seconds,
            "rtf": transcribe_seconds / (len(audio) / SAMPLE_RATE),
            "segments": len(result["segments"]),
            "words": words_count,
            "tokens": tokens_count,
            "comparison": comparison,
            "warnings": warnings,
        },
    )
    save_file_index(output_dir)

    print("\n최종 STT 결과")
    print(result["text"])
    print("\n실행 시간")
    print(f"전처리: {format_elapsed(preprocess_seconds)}")
    print(f"모델 로드 + STT: {format_elapsed(transcribe_seconds)}")
    print(f"산출물 저장: {format_elapsed(artifacts_seconds)}")
    print(f"전체: {format_elapsed(total_seconds)} ({total_seconds:.2f}초)")
    print(f"\n모든 산출물: {output_dir}")
    print(f"구간별 전체 전사: {labeled_transcript}")
    print(f"산출물 설명: {output_dir / 'FILES.txt'}")


def inspect_wav(wav_path: Path, model_name: str) -> None:
    if model_name == CPP_MODEL_NAME:
        inspect_wav_cpp(wav_path, model_name)
        return
    overall_started = time.perf_counter()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    ensure_mps()
    wav_path = resolve_audio(wav_path)
    output_dir = inspect_output_dir(wav_path, model_name)
    print(f"입력: {wav_path}")
    print(f"모델: {model_name}")
    estimate = show_runtime_estimate(wav_path, model_name)
    print("모델을 불러오는 중...")
    model_started = time.perf_counter()
    model = whisper.load_model(model_name, device="mps")
    model_seconds = time.perf_counter() - model_started

    print("Whisper 입력과 언어 확률을 계산하는 중...")
    preprocess_started = time.perf_counter()
    audio = whisper.load_audio(str(wav_path))
    mel = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
    np.save(output_dir / "audio_16k_mono.npy", audio)
    mel_array = mel.cpu().numpy()
    np.save(output_dir / "log_mel_spectrogram.npy", mel_array)
    write_json(
        output_dir / "log_mel_summary.json",
        {
            "shape": list(mel_array.shape),
            "dtype": str(mel_array.dtype),
            "min": float(mel_array.min()),
            "max": float(mel_array.max()),
            "mean": float(mel_array.mean()),
            "std": float(mel_array.std()),
        },
    )
    language_input = whisper.pad_or_trim(mel, N_FRAMES).to(model.device).to(torch.float16)
    _, probabilities = model.detect_language(language_input)
    language_rows = [
        {"language": language, "probability": probability}
        for language, probability in sorted(probabilities.items(), key=lambda item: -item[1])
    ]
    write_csv(output_dir / "language_probabilities.csv", ["language", "probability"], language_rows)
    detected_language = language_rows[0]["language"]
    preprocess_seconds = time.perf_counter() - preprocess_started

    print(f"감지 언어: {detected_language}")
    print("STT를 실행하는 중... (진행률과 ETA)")
    import whisper.timing as whisper_timing

    original_dtw = whisper_timing.dtw

    def mps_safe_dtw(tensor):
        if tensor.device.type == "mps":
            return whisper_timing.dtw_cpu(tensor.cpu().double().numpy())
        return original_dtw(tensor)

    whisper_timing.dtw = mps_safe_dtw
    transcribe_started = time.perf_counter()
    try:
        result = model.transcribe(
            audio,
            language=detected_language,
            task="transcribe",
            fp16=True,
            temperature=INSPECT_TEMPERATURES,
            condition_on_previous_text=False,
            compression_ratio_threshold=INSPECT_COMPRESSION_RATIO_THRESHOLD,
            logprob_threshold=INSPECT_LOGPROB_THRESHOLD,
            no_speech_threshold=INSPECT_NO_SPEECH_THRESHOLD,
            word_timestamps=True,
            verbose=False,
        )
    finally:
        whisper_timing.dtw = original_dtw
    transcribe_seconds = time.perf_counter() - transcribe_started

    artifacts_started = time.perf_counter()
    write_json(output_dir / "result.json", result)
    save_standard_transcripts(result, wav_path, output_dir)
    save_result_tables(result, model, output_dir)
    labeled_transcript = save_labeled_transcript(result, wav_path, output_dir)
    comparison = save_reference_comparison(wav_path, result["text"].strip(), output_dir)
    input_info = save_audio_info(wav_path, output_dir)
    warnings = save_audio_images(wav_path, output_dir)
    artifacts_seconds = time.perf_counter() - artifacts_started
    total_seconds = time.perf_counter() - overall_started
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(
        output_dir / "run_summary.json",
        {
            "input": str(wav_path),
            "model": model_name,
            "device": "mps",
            "fp16": True,
            "decoding": {
                "temperature": list(INSPECT_TEMPERATURES),
                "condition_on_previous_text": False,
                "compression_ratio_threshold": INSPECT_COMPRESSION_RATIO_THRESHOLD,
                "logprob_threshold": INSPECT_LOGPROB_THRESHOLD,
                "no_speech_threshold": INSPECT_NO_SPEECH_THRESHOLD,
            },
            "detected_language": detected_language,
            "detected_language_probability": language_rows[0]["probability"],
            "audio_samples": len(audio),
            "audio_seconds": len(audio) / SAMPLE_RATE,
            "runtime_estimate": estimate,
            "started_at": started_at,
            "finished_at": finished_at,
            "model_load_seconds": model_seconds,
            "preprocess_seconds": preprocess_seconds,
            "transcribe_seconds": transcribe_seconds,
            "artifacts_seconds": artifacts_seconds,
            "total_seconds": total_seconds,
            "rtf": transcribe_seconds / (len(audio) / SAMPLE_RATE),
            "segments": len(result.get("segments", [])),
            "words": sum(len(segment.get("words", [])) for segment in result.get("segments", [])),
            "tokens": sum(len(segment.get("tokens", [])) for segment in result.get("segments", [])),
            "comparison": comparison,
            "input_info_file": "input_info.json",
            "warnings": warnings,
        },
    )
    save_file_index(output_dir)

    print("\n최종 STT 결과")
    print(result["text"].strip())
    print("\n실행 시간")
    print(f"모델 로드: {format_elapsed(model_seconds)}")
    print(f"전처리/언어 감지: {format_elapsed(preprocess_seconds)}")
    print(f"STT: {format_elapsed(transcribe_seconds)}")
    print(f"산출물 저장: {format_elapsed(artifacts_seconds)}")
    print(f"전체: {format_elapsed(total_seconds)} ({total_seconds:.2f}초)")
    print(f"\n모든 산출물: {output_dir}")
    print(f"구간별 전체 전사: {labeled_transcript}")
    print(f"산출물 설명: {output_dir / 'FILES.txt'}")


def load_records() -> dict[str, dict[str, str]]:
    if not PREDICTIONS_PATH.exists():
        return {}
    with PREDICTIONS_PATH.open(encoding="utf-8", newline="") as file:
        return {row["sample_id"]: row for row in csv.DictReader(file)}


def write_records(records: dict[str, dict[str, str]]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS_DIR / ".predictions.tmp"
    ordered = sorted(records.values(), key=lambda row: row["sample_id"])
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    temporary.replace(PREDICTIONS_PATH)


def make_record(sample: Sample, prediction: str, seconds: float) -> dict[str, str]:
    ref_chars = normalize_chars(sample.reference)
    pred_chars = normalize_chars(prediction)
    ref_words = normalize_words(sample.reference).split()
    pred_words = normalize_words(prediction).split()
    return {
        "sample_id": sample.sample_id,
        "status": "ok",
        "wav": sample.wav.relative_to(ROOT).as_posix(),
        "start": f"{sample.start:.3f}",
        "end": f"{sample.end:.3f}",
        "duration": f"{sample.duration:.3f}",
        "reference": sample.reference,
        "prediction": prediction,
        "char_errors": str(edit_distance(ref_chars, pred_chars)),
        "ref_chars": str(len(ref_chars)),
        "word_errors": str(edit_distance(ref_words, pred_words)),
        "ref_words": str(len(ref_words)),
        "seconds": f"{seconds:.6f}",
        "error": "",
    }


def error_record(sample: Sample, exc: Exception) -> dict[str, str]:
    return {
        "sample_id": sample.sample_id,
        "status": "error",
        "wav": sample.wav.relative_to(ROOT).as_posix(),
        "start": f"{sample.start:.3f}",
        "end": f"{sample.end:.3f}",
        "duration": f"{sample.duration:.3f}",
        "reference": sample.reference,
        "prediction": "",
        "char_errors": "",
        "ref_chars": "",
        "word_errors": "",
        "ref_words": "",
        "seconds": "",
        "error": f"{type(exc).__name__}: {exc}",
    }


def summarize(selected: list[Sample], records: dict[str, dict[str, str]], mode: str) -> dict:
    selected_rows = [records[s.sample_id] for s in selected if s.sample_id in records]
    completed = [row for row in selected_rows if row["status"] == "ok"]
    failed = [row for row in selected_rows if row["status"] == "error"]
    char_errors = sum(int(row["char_errors"]) for row in completed)
    ref_chars = sum(int(row["ref_chars"]) for row in completed)
    word_errors = sum(int(row["word_errors"]) for row in completed)
    ref_words = sum(int(row["ref_words"]) for row in completed)
    audio_seconds = sum(float(row["duration"]) for row in completed)
    inference_seconds = sum(float(row["seconds"]) for row in completed)
    return {
        "mode": mode,
        "model": MODEL,
        "total": len(selected),
        "completed": len(completed),
        "failed": len(failed),
        "cer": char_errors / ref_chars if ref_chars else None,
        "wer": word_errors / ref_words if ref_words else None,
        "rtf": inference_seconds / audio_seconds if audio_seconds else None,
        "audio_hours": audio_seconds / 3600,
        "inference_seconds": inference_seconds,
    }


def show_summary(summary: dict) -> None:
    percent = lambda value: "-" if value is None else f"{value * 100:.2f}%"
    rtf = "-" if summary["rtf"] is None else f"{summary['rtf']:.3f}"
    print("\n평가 결과")
    print(f"완료: {summary['completed']} / {summary['total']}개")
    print(f"CER: {percent(summary['cer'])}")
    print(f"WER: {percent(summary['wer'])}")
    print(f"RTF: {rtf}")
    print(f"결과 파일: {PREDICTIONS_PATH}")


def evaluate(*, test_mode: bool) -> None:
    ensure_mps()
    all_samples = discover_samples()
    if test_mode:
        selected = random.Random(TEST_SEED).sample(all_samples, min(TEST_SIZE, len(all_samples)))
        selected.sort(key=lambda sample: sample.sample_id)
        mode = "test"
    else:
        selected = all_samples
        mode = "full"

    records = load_records()
    pending = [sample for sample in selected if records.get(sample.sample_id, {}).get("status") != "ok"]
    print(f"모델: {MODEL}")
    print(f"평가 대상: {len(selected)}개")
    print(f"남은 음성: {len(pending)}개")

    if pending:
        print("모델을 불러오는 중...")
        model = whisper.load_model(MODEL, device="mps")

        @lru_cache(maxsize=2)
        def cached_audio(path: str) -> np.ndarray:
            return load_wav(Path(path))

        try:
            for index, sample in enumerate(tqdm(pending, desc="평가", unit="개"), 1):
                try:
                    audio = cached_audio(str(sample.wav))
                    start = max(0, round(sample.start * SAMPLE_RATE))
                    end = min(audio.size, round(sample.end * SAMPLE_RATE))
                    if end <= start:
                        raise ValueError("음성 구간이 파일 범위를 벗어났습니다.")
                    segment = np.ascontiguousarray(audio[start:end], dtype=np.float32)
                    started = time.perf_counter()
                    result = model.transcribe(
                        segment,
                        language="ko",
                        task="transcribe",
                        fp16=True,
                        temperature=0.0,
                        condition_on_previous_text=False,
                        without_timestamps=True,
                        verbose=None,
                    )
                    records[sample.sample_id] = make_record(
                        sample, result["text"].strip(), time.perf_counter() - started
                    )
                except Exception as exc:
                    records[sample.sample_id] = error_record(sample, exc)
                if index % 10 == 0:
                    write_records(records)
        finally:
            write_records(records)

    summary = summarize(selected, records, mode)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    show_summary(summary)
