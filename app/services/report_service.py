from uuid import UUID 

from app.reporting.pdf_renderer import render_pdf 
from app.repositories.report_repositories import ReportRepository 


class ReportService:
    def __init__(self, repository: ReportRepository | None = None):
        self.repository = repository if repository is not None else ReportRepository() 

    def export(self, job_id: UUID, proposal_id: int | None = None) -> tuple[bytes, str]:
        snapshot = self.repository.load(job_id, proposal_id)
        data = render_pdf(snapshot)
        version = f"proposal-{snapshot.proposal_id}" if snapshot.proposal_id is not None else "job-only"
        return data, f"job-intelligence-{job_id}-{version}.pdf"

report_service = ReportService()