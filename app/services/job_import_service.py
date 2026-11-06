from app.models.job_import import HtmlJobImportRequest, HtmlJobImportResponse
from app.services.job_service import JobService, job_service
from app.sources.base import JobSource, JobSourceError
from app.sources.html_sources import ExampleHtmlJobSource, JsonLdJobSource


class JobImportService:
    def __init__(self, jobs: JobService | None = None, sources: dict[str, JobSource] | None = None):
        self.jobs = jobs if jobs is not None else job_service
        self.sources = sources if sources is not None else {
            "jsonld": JsonLdJobSource(),
            "example_html": ExampleHtmlJobSource(),
        }

    def import_html(self, request: HtmlJobImportRequest) -> HtmlJobImportResponse:
        source = self.sources.get(request.parser)
        if source is None:
            raise JobSourceError("Requested parser is not registered")
        parsed = source.parse(
            request.html, str(request.source_url) if request.source_url is not None else None,
            request.job_index,
        )
        job = self.jobs.create_job(parsed.data)
        return HtmlJobImportResponse(job=job, parser=request.parser, warnings=parsed.warnings)


job_import_service = JobImportService()