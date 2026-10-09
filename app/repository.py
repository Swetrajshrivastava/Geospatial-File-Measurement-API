from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from app.models import FeatureMeasurement, FileSummary


@dataclass(frozen=True)
class ProcessedFile:
    summary: FileSummary
    features: list[FeatureMeasurement]


class InMemoryFileRepository:
    """Thread-safe metadata store. Swap this adapter for a database in production."""

    def __init__(self) -> None:
        self._items: dict[str, ProcessedFile] = {}
        self._lock = RLock()

    def save(self, item: ProcessedFile) -> None:
        with self._lock:
            self._items[item.summary.id] = item

    def get(self, file_id: str) -> ProcessedFile | None:
        with self._lock:
            return self._items.get(file_id)


repository = InMemoryFileRepository()
