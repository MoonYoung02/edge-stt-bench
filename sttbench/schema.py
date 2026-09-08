"""Canonical output types shared by every STT adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Token:
    text: str
    id: int | None = None
    start: float | None = None
    end: float | None = None
    confidence: float | None = None


@dataclass
class Word:
    text: str
    start: float | None = None
    end: float | None = None
    confidence: float | None = None


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    speaker: str | None = None
    confidence: float | None = None
    words: list[Word] = field(default_factory=list)
    tokens: list[Token] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Transcript:
    text: str
    language: str | None
    segments: list[Segment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

