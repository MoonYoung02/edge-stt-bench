"""Reader for the Korean conversational speech corpus TXT format."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

LINE = re.compile(
    r"^\[(?P<start>\d+(?:\.\d+)?),(?P<end>\d+(?:\.\d+)?)\]\s*"
    r"(?P<speaker>\S+)\s+(?P<gender>\S+)\s+(?P<text>.*)$"
)
DATASET_ID = "MagicHub/korean-conversational-speech-corpus"


@dataclass(frozen=True)
class KcscSample:
    id: str
    audio: Path
    reference: Path


@dataclass(frozen=True)
class ReferenceSegment:
    start: float
    end: float
    speaker: str
    gender: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_reference(path: Path) -> list[ReferenceSegment]:
    return parse_reference_text(read_text(path), source=str(path))


def parse_reference_text(
    text: str, *, source: str = "<string>"
) -> list[ReferenceSegment]:
    """Parse the `[start,end]\tspeaker\tgender\ttext` KCSC reference format.

    Shared by the desktop evaluator (reading a TXT file via [parse_reference])
    and the mobile result importer (scoring the reference string the app
    already loaded into a run's `result.reference`), so both sides extract
    the same plain transcript instead of diffing against timestamp/speaker
    columns by mistake.
    """
    segments: list[ReferenceSegment] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = LINE.match(stripped)
        if not match:
            raise ValueError(f"참조 텍스트 형식을 읽을 수 없습니다: {source}:{line_number}")
        values = match.groupdict()
        segments.append(
            ReferenceSegment(
                start=float(values["start"]),
                end=float(values["end"]),
                speaker=values["speaker"],
                gender=values["gender"],
                text=values["text"],
            )
        )
    return segments


def find_reference(audio_path: Path, project_root: Path) -> Path | None:
    candidates = [
        project_root / "data" / "kcsc" / "TXT" / f"{audio_path.stem}.txt",
        audio_path.parent.parent / "TXT" / f"{audio_path.stem}.txt",
        audio_path.with_suffix(".txt"),
    ]
    return next((path for path in candidates if path.exists()), None)


def discover_samples(
    dataset_root: Path, *, limit: int | None = None
) -> list[KcscSample]:
    """Return KCSC WAV/TXT pairs in a stable order.

    Missing reference files stay in the returned list so a batch evaluation can
    record a per-sample failure instead of silently dropping data.
    """

    wav_dir = dataset_root / "WAV"
    txt_dir = dataset_root / "TXT"
    if not wav_dir.is_dir():
        raise FileNotFoundError(f"KCSC WAV 폴더가 없습니다: {wav_dir}")
    if not txt_dir.is_dir():
        raise FileNotFoundError(f"KCSC TXT 폴더가 없습니다: {txt_dir}")
    audio_paths = sorted(
        (
            path
            for path in wav_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".wav"
        ),
        key=lambda path: path.name,
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("limit은 1 이상이어야 합니다.")
        audio_paths = audio_paths[:limit]
    return [
        KcscSample(id=audio.stem, audio=audio, reference=txt_dir / f"{audio.stem}.txt")
        for audio in audio_paths
    ]


def download_dataset(project_root: Path) -> Path:
    """Download the academic-use KCSC files into data/kcsc."""

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "KCSC 다운로드에는 huggingface-hub 패키지가 필요합니다."
        ) from exc

    dataset_root = project_root / "data" / "kcsc"
    dataset_root.mkdir(parents=True, exist_ok=True)
    print(f"KCSC 데이터를 내려받는 중: {DATASET_ID}")
    snapshot_download(
        repo_id=DATASET_ID,
        repo_type="dataset",
        local_dir=dataset_root,
        allow_patterns=[
            "WAV/*.wav",
            "TXT/*.txt",
            "README.md",
            "README.txt",
            "AUDIOINFO.txt",
            "SPKINFO.txt",
        ],
    )
    samples = discover_samples(dataset_root)
    print(f"KCSC 준비 완료: {len(samples)}개 WAV / {dataset_root}")
    return dataset_root
