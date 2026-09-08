"""Small JSONL manifest format for future repeatable benchmark suites."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetItem:
    id: str
    audio: Path
    reference: Path | None = None
    scenario: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def load_manifest(path: Path) -> list[DatasetItem]:
    items: list[DatasetItem] = []
    base = path.parent
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            audio = Path(raw["audio"])
            reference = Path(raw["reference"]) if raw.get("reference") else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"잘못된 manifest입니다: {path}:{line_number}") from exc
        items.append(
            DatasetItem(
                id=str(raw.get("id", audio.stem)),
                audio=audio if audio.is_absolute() else base / audio,
                reference=(reference if reference and reference.is_absolute() else base / reference)
                if reference
                else None,
                scenario=raw.get("scenario"),
                tags=list(raw.get("tags", [])),
                metadata=dict(raw.get("metadata", {})),
            )
        )
    return items
