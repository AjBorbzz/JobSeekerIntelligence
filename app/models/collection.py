from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.schemas import Job, JobCreate


class GreenhouseSearchRequest(BaseModel):
    board_token: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("query must contain at least two nonblank characters")
        return cleaned


class GreenhouseImportRequest(BaseModel):
    board_token: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    external_id: int = Field(gt=0, strict=True)


class GreenhouseCandidate(BaseModel):
    external_id: int
    data: JobCreate
    location: str | None = None
    warnings: list[str] = Field(default_factory=list)


class GreenhouseSearchResponse(BaseModel):
    provider: Literal["greenhouse"] = "greenhouse"
    board_token: str
    query: str
    fetched_count: int
    matched_count: int
    cached: bool
    candidates: list[GreenhouseCandidate]
    warnings: list[str] = Field(default_factory=list)


class GreenhouseImportResponse(BaseModel):
    provider: Literal["greenhouse"] = "greenhouse"
    board_token: str
    external_id: int
    created: bool
    job: Job
    warnings: list[str] = Field(default_factory=list)