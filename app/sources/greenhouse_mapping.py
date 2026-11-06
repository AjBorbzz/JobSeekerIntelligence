from datetime import datetime
from html import unescape

from pydantic import BaseModel, Field, ValidationError

from app.models.collection import GreenhouseCandidate
from app.sources.base import JobSourceError
from app.sources.html_sources import clean_text, safe_url, validated_job


class GreenhousePost(BaseModel):
    id: int = Field(gt=0, strict=True)
    title: str
    content: str
    absolute_url: str | None = None
    company_name: str | None = None
    updated_at: str | None = None
    location: dict | None = None


def normalize_post(raw: dict) -> GreenhouseCandidate:
    if raw.get("internal_job_id", "not-provided") is None:
        raise JobSourceError("General-interest prospect posts are not supported")
    try:
        post = GreenhousePost.model_validate(raw)
    except ValidationError as exc:
        raise JobSourceError("Provider job is missing supported fields") from exc

    warnings = []
    updated = None
    if post.updated_at:
        try:
            updated = datetime.fromisoformat(post.updated_at.replace("Z", "+00:00")).date()
        except ValueError:
            warnings.append("Unrecognized updated_at was not mapped.")
    parsed = validated_job({
        "title": clean_text(unescape(post.title)),
        "job_overview": clean_text(unescape(post.content)),
        "company": clean_text(post.company_name) if post.company_name else None,
        "source_url": safe_url(post.absolute_url, warnings),
        "date_updated": updated,
    }, warnings)
    location = post.location.get("name") if post.location else None
    return GreenhouseCandidate(
        external_id=post.id, data=parsed.data,
        location=location if isinstance(location, str) else None, warnings=parsed.warnings,
    )