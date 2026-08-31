from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    polygon: list[list[int]]


@dataclass(frozen=True)
class OcrDocument:
    text: str
    lines: list[OcrLine]
    confidence: float | None
    raw: dict[str, Any]
    provider: str
    model: str
    duration_ms: int


class OcrEngine(Protocol):
    def read(self, path: str) -> OcrDocument: ...
