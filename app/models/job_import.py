from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.models.schemas import Job

HtmlParserName = Literal["jsonld", "example_html"]


class HtmlJobImportRequest(BaseModel):
    html: str = Field(min_length=20, max_length=500_000)
    parser: HtmlParserName = "jsonld"
    source_url: HttpUrl | None = None
    job_index: int | None = Field(default=None, ge=0)

    @field_validator("source_url")
    @classmethod
    def reject_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username is not None or value.password is not None):
            raise ValueError("source_url must not contain credentials")
        return value


class HtmlJobImportResponse(BaseModel):
    job: Job
    parser: HtmlParserName
    warnings: list[str] = Field(default_factory=list)