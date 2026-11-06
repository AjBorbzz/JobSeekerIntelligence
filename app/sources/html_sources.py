import json

from bs4 import BeautifulSoup
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.models.schemas import JobCreate, WorkType
from app.sources.base import JobSourceError, ParsedJob

URL_ADAPTER = TypeAdapter(HttpUrl)
WORK_TYPES = {
    "FULL_TIME": WorkType.FULL_TIME,
    "PART_TIME": WorkType.PART_TIME,
    "CONTRACT": WorkType.CONTRACT,
    "CONTRACTOR": WorkType.CONTRACT,
    "FREELANCE": WorkType.FREELANCE,
}


def clean_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup.select("script, style, noscript, template, head, [hidden]"):
        if tag.parent is not None:
            tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def text_value(value) -> str | None:
    return clean_text(value) if isinstance(value, str) else None


def safe_url(value, warnings: list[str]) -> str | None:
    if value is None:
        return None
    try:
        url = URL_ADAPTER.validate_python(value)
        if url.username is not None or url.password is not None:
            raise ValueError("Credentials are not allowed")
        return str(url)
    except (ValueError, ValidationError):
        warnings.append("Invalid source URL was ignored.")
        return None


def work_type(value, warnings: list[str]) -> WorkType:
    if value is None:
        return WorkType.UNKNOWN
    values = value if isinstance(value, list) else [value]
    labels = {
        item.strip().upper().replace("-", "_").replace(" ", "_")
        for item in values if isinstance(item, str) and item.strip()
    }
    if len(labels) == 1 and len(values) == len([x for x in values if isinstance(x, str)]):
        mapped = WORK_TYPES.get(next(iter(labels)))
        if mapped is not None:
            return mapped
    warnings.append("Unsupported or ambiguous employment type was stored as unknown.")
    return WorkType.UNKNOWN


def validated_job(values: dict, warnings: list[str]) -> ParsedJob:
    try:
        return ParsedJob(JobCreate.model_validate(values), warnings)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors()})
        raise JobSourceError(f"Parsed job failed validation: {', '.join(fields)}") from exc


def job_postings(document) -> list[dict]:
    found = []
    stack = [document]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > 5000:
            raise JobSourceError("JSON-LD contains too many graph nodes")
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            types = node.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any(value in ("JobPosting", "https://schema.org/JobPosting", "http://schema.org/JobPosting")
                   for value in types):
                found.append(node)
            for key in reversed(("@graph", "mainEntity")):
                child = node.get(key)
                if isinstance(child, (list, dict)):
                    stack.append(child)
    return found


def reject_nonfinite(value: str):
    raise ValueError(f"Non-finite JSON value: {value}")


class JsonLdJobSource:
    def parse(self, html: str, source_url: str | None = None, job_index: int | None = None) -> ParsedJob:
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        malformed = 0
        for script in soup.find_all("script"):
            mime = str(script.get("type") or "").split(";", 1)[0].strip().casefold()
            if mime != "application/ld+json":
                continue
            content = str(script.string or "").lstrip("\ufeff")
            try:
                document = json.loads(content, parse_constant=reject_nonfinite)
            except (ValueError, RecursionError):
                malformed += 1
                continue
            candidates.extend(job_postings(document))

        if not candidates:
            raise JobSourceError("No readable JSON-LD JobPosting found; use manual input or a supported HTML adapter")
        if job_index is None:
            if len(candidates) != 1:
                raise JobSourceError(f"Found {len(candidates)} JobPosting entries; supply a zero-based job_index")
            job_index = 0
        if job_index < 0 or job_index >= len(candidates):
            raise JobSourceError("job_index is outside the available JobPosting entries")

        node = candidates[job_index]
        warnings = [f"Skipped {malformed} malformed JSON-LD block(s)."] if malformed else []
        organization = node.get("hiringOrganization")
        company = text_value(organization.get("name")) if isinstance(organization, dict) else None
        if organization is not None and company is None:
            warnings.append("Unsupported hiringOrganization was not mapped.")
        for field in ("baseSalary", "workHours", "datePosted", "dateModified"):
            if field in node:
                warnings.append(f"{field} is not mapped in Phase 9; no corresponding value was inferred.")

        return validated_job({
            "title": text_value(node.get("title")),
            "company": company,
            "source_url": safe_url(source_url if source_url is not None else node.get("url"), warnings),
            "type_of_work": work_type(node.get("employmentType"), warnings),
            "job_overview": text_value(node.get("description")),
        }, warnings)


class ExampleHtmlJobSource:
    def parse(self, html: str, source_url: str | None = None, job_index: int | None = None) -> ParsedJob:
        if job_index is not None:
            raise JobSourceError("job_index is only supported by the JSON-LD adapter")
        soup = BeautifulSoup(html, "html.parser")
        warnings = []

        def field(name: str, required: bool = False) -> str | None:
            nodes = soup.select(f"[data-job-{name}]")
            if len(nodes) > 1 or (required and len(nodes) != 1):
                raise JobSourceError(f"Expected exactly one data-job-{name} element")
            return clean_text(str(nodes[0])) if nodes else None

        return validated_job({
            "title": field("title", required=True),
            "company": field("company"),
            "source_url": safe_url(source_url, warnings),
            "type_of_work": work_type(field("work-type"), warnings),
            "job_overview": field("description", required=True),
        }, warnings)