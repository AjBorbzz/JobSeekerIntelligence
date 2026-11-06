from app.models.collection import (
    GreenhouseImportRequest, GreenhouseImportResponse, GreenhouseSearchRequest, GreenhouseSearchResponse,
)
from app.repositories.external_job_repository import ExternalJobRepository
from app.sources.base import JobSourceError
from app.sources.greenhouse_client import CollectionError, GreenhouseClient
from app.sources.greenhouse_mapping import normalize_post


class GreenhouseService:
    def __init__(self, client: GreenhouseClient | None = None, repository: ExternalJobRepository | None = None):
        self.client = client if client is not None else GreenhouseClient()
        self.repository = repository if repository is not None else ExternalJobRepository()

    def search(self, request: GreenhouseSearchRequest) -> GreenhouseSearchResponse:
        payload, cached = self.client.fetch(request.board_token)
        rows = payload.get("jobs")
        if not isinstance(rows, list):
            raise CollectionError(502, "Provider response is missing its jobs array")
        if len(rows) > 10_000:
            raise CollectionError(502, "Provider job count exceeds the configured limit")
        tokens = request.query.casefold().split()
        matches = []
        invalid = 0
        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise JobSourceError("Invalid job entry")
                candidate = normalize_post(row)
            except JobSourceError:
                invalid += 1
                continue
            text = (candidate.data.title + " " + candidate.data.job_overview).casefold()
            if all(token in text for token in tokens):
                matches.append(candidate)
        return GreenhouseSearchResponse(
            board_token=request.board_token, query=request.query, fetched_count=len(rows),
            matched_count=len(matches), cached=cached, candidates=matches[:request.limit],
            warnings=[f"Skipped {invalid} unsupported or invalid entries."] if invalid else [],
        )

    def import_job(self, request: GreenhouseImportRequest) -> GreenhouseImportResponse:
        existing = self.repository.find(request.board_token, request.external_id)
        if existing is not None:
            return GreenhouseImportResponse(
                board_token=request.board_token, external_id=request.external_id, created=False, job=existing,
            )
        payload, _ = self.client.fetch(request.board_token, request.external_id)
        try:
            candidate = normalize_post(payload)
        except JobSourceError as exc:
            raise CollectionError(502, "Selected provider job could not be normalized") from exc
        if candidate.external_id != request.external_id:
            raise CollectionError(502, "Provider returned a different job post ID")
        job, created = self.repository.import_once(request.board_token, request.external_id, candidate.data)
        return GreenhouseImportResponse(
            board_token=request.board_token, external_id=request.external_id, created=created, job=job,
            warnings=candidate.warnings,
        )


greenhouse_service = GreenhouseService()