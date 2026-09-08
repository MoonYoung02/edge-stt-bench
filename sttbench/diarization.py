"""Run isolated speaker diarization and align it with STT word timestamps."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time

from sttbench.artifacts import save_file_index, write_json
from sttbench.progress import format_elapsed
from sttbench.schema import Transcript, Word

MODEL_ID = "pyannote/speaker-diarization-community-1"


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class SpeakerUtterance:
    start: float
    end: float
    speaker: str
    text: str
    words: int


@dataclass
class DiarizationResult:
    model: str
    device: str
    seconds: float
    regular: list[SpeakerTurn]
    exclusive: list[SpeakerTurn]
    speakers: list[str]
    log: str


def runtime_python(project_root: Path) -> Path:
    return project_root / ".venv-diarization" / "bin" / "python"


def check_runtime(project_root: Path) -> tuple[bool, str]:
    executable = runtime_python(project_root)
    if not executable.is_file():
        return False, ".venv-diarization 없음"
    process = subprocess.run(
        [str(executable), "-c", "import pyannote.audio; print(pyannote.audio.__version__)"],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        return False, "pyannote.audio를 불러올 수 없음"
    return True, f"pyannote.audio {process.stdout.strip()}"


def run_diarization(
    project_root: Path,
    audio_path: Path,
    raw_dir: Path,
    *,
    num_speakers: int | None = None,
    device: str = "auto",
) -> DiarizationResult:
    executable = runtime_python(project_root)
    if not executable.is_file():
        raise RuntimeError("화자 분리 환경이 없습니다: .venv-diarization")
    output_path = raw_dir / "pyannote_diarization.json"
    command = [
        str(executable),
        str(Path(__file__).with_name("diarization_runtime.py")),
        str(audio_path),
        str(output_path),
        "--device",
        device,
    ]
    if num_speakers is not None:
        command.extend(["--speakers", str(num_speakers)])

    print("화자 분리를 실행하는 중... (진행률과 ETA)")
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYANNOTE_METRICS_ENABLED": "0"},
    )
    lines: list[str] = []
    last_progress = -1
    current_step = ""
    stage_started = started
    assert process.stdout is not None
    try:
        for line in process.stdout:
            lines.append(line)
            match = re.search(r"DIARIZATION_PROGRESS\s+(\d+)\s+(\d+)\s+(\S+)", line)
            if not match:
                continue
            completed, total = map(int, match.groups()[:2])
            step = match.group(3)
            if total <= 0:
                continue
            if step != current_step:
                current_step = step
                last_progress = -1
                stage_started = time.perf_counter()
            progress = min(100, round(completed / total * 100))
            if progress == last_progress:
                continue
            last_progress = progress
            elapsed = time.perf_counter() - stage_started
            remaining = elapsed * (100 - progress) / progress if progress else 0.0
            print(
                f"\r화자 분리 [{step}]: {progress:3d}% | 경과 {format_elapsed(elapsed)} | "
                + (
                    f"남은 시간 약 {format_elapsed(remaining)}"
                    if progress
                    else "남은 시간 계산 중"
                ),
                end="",
                flush=True,
            )
        returncode = process.wait()
    except BaseException:
        process.terminate()
        process.wait()
        raise
    seconds = time.perf_counter() - started
    if last_progress >= 0:
        print()
    log = "COMMAND\n" + " ".join(command) + "\n\nOUTPUT\n" + "".join(lines)
    (raw_dir / "pyannote.log").write_text(log, encoding="utf-8")
    if returncode:
        raise RuntimeError(f"화자 분리 실패. 로그: {raw_dir / 'pyannote.log'}")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    return DiarizationResult(
        model=payload["model"],
        device=payload["device"],
        seconds=seconds,
        regular=[SpeakerTurn(**turn) for turn in payload["diarization"]],
        exclusive=[SpeakerTurn(**turn) for turn in payload["exclusive_diarization"]],
        speakers=list(payload["speakers"]),
        log=log,
    )


def save_diarization_artifacts(
    sample_dir: Path,
    audio_path: Path,
    transcript: Transcript,
    result: DiarizationResult,
) -> dict:
    regular = [asdict(turn) for turn in result.regular]
    exclusive = [asdict(turn) for turn in result.exclusive]
    overlaps = overlap_regions(result.regular)
    utterances = align_transcript(transcript, result.exclusive)
    write_json(sample_dir / "diarization.json", regular)
    write_json(sample_dir / "exclusive_diarization.json", exclusive)
    write_json(sample_dir / "overlap_segments.json", overlaps)
    write_json(sample_dir / "speaker_transcript.json", [asdict(item) for item in utterances])
    save_rttm(sample_dir / "diarization.rttm", audio_path.stem, result.regular)
    save_speaker_transcript(sample_dir / "speaker_transcript.txt", utterances)
    save_file_index(sample_dir)
    return {
        "model": result.model,
        "device": result.device,
        "seconds": result.seconds,
        "speakers": result.speakers,
        "speaker_count": len(result.speakers),
        "turns": len(result.regular),
        "exclusive_turns": len(result.exclusive),
        "overlap_regions": len(overlaps),
        "speaker_utterances": len(utterances),
    }


def assign_speaker(start: float, end: float, turns: list[SpeakerTurn]) -> str:
    if not turns:
        return "unknown"
    overlaps = [max(0.0, min(end, turn.end) - max(start, turn.start)) for turn in turns]
    best_index = max(range(len(turns)), key=overlaps.__getitem__)
    if overlaps[best_index] > 0:
        return turns[best_index].speaker
    midpoint = (start + end) / 2
    nearest = min(turns, key=lambda turn: min(abs(midpoint - turn.start), abs(midpoint - turn.end)))
    distance = min(abs(midpoint - nearest.start), abs(midpoint - nearest.end))
    return nearest.speaker if distance <= 2.0 else "unknown"


def align_transcript(transcript: Transcript, turns: list[SpeakerTurn]) -> list[SpeakerUtterance]:
    assigned: list[tuple[Word, str]] = []
    for segment in transcript.segments:
        if segment.words:
            for word in segment.words:
                if word.start is None or word.end is None:
                    continue
                assigned.append((word, assign_speaker(word.start, word.end, turns)))
        elif segment.text:
            assigned.append(
                (
                    Word(text=segment.text, start=segment.start, end=segment.end),
                    assign_speaker(segment.start, segment.end, turns),
                )
            )
    utterances: list[SpeakerUtterance] = []
    active: dict | None = None
    for word, speaker in assigned:
        assert word.start is not None and word.end is not None
        if active and (active["speaker"] != speaker or word.start - active["end"] > 1.5):
            utterances.append(_finish_utterance(active))
            active = None
        if active is None:
            active = {
                "start": word.start,
                "end": word.end,
                "speaker": speaker,
                "parts": [word.text.strip()],
            }
        else:
            active["end"] = max(active["end"], word.end)
            active["parts"].append(word.text.strip())
    if active:
        utterances.append(_finish_utterance(active))
    return utterances


def _finish_utterance(active: dict) -> SpeakerUtterance:
    parts = [part for part in active["parts"] if part]
    return SpeakerUtterance(
        start=active["start"],
        end=active["end"],
        speaker=active["speaker"],
        text=" ".join(parts),
        words=len(parts),
    )


def overlap_regions(turns: list[SpeakerTurn]) -> list[dict]:
    boundaries = sorted({point for turn in turns for point in (turn.start, turn.end)})
    regions: list[dict] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        speakers = sorted({turn.speaker for turn in turns if turn.start <= midpoint < turn.end})
        if len(speakers) < 2:
            continue
        if regions and regions[-1]["speakers"] == speakers and abs(regions[-1]["end"] - start) < 1e-6:
            regions[-1]["end"] = end
        else:
            regions.append({"start": start, "end": end, "speakers": speakers})
    return regions


def save_rttm(path: Path, recording_id: str, turns: list[SpeakerTurn]) -> None:
    lines = [
        f"SPEAKER {recording_id} 1 {turn.start:.3f} {turn.end - turn.start:.3f} "
        f"<NA> <NA> {turn.speaker} <NA> <NA>"
        for turn in turns
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def save_speaker_transcript(path: Path, utterances: list[SpeakerUtterance]) -> None:
    lines = [
        f"[{item.start:.3f},{item.end:.3f}]\t{item.speaker}\tunknown\t{item.text}"
        for item in utterances
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
