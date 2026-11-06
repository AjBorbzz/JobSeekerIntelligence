from dataclasses import dataclass
from typing import Protocol

from app.models.schemas import JobCreate


class JobSourceError(ValueError):
    pass


@dataclass
class ParsedJob:
    data: JobCreate
    warnings: list[str]


class JobSource(Protocol):
    def parse(self, html: str, source_url: str | None = None, job_index: int | None = None) -> ParsedJob:
        ...