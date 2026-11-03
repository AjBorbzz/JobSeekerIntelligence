from uuid import UUID

from app.llm.job_analyzer import JobAnalyzer
from app.models.schemas import Job, JobAnalysis
from app.repositories.analysis_repositories import AnalysisRepository


class AnalysisService:
    def __init__(self, analyzer: JobAnalyzer | None = None, repository: AnalysisRepository | None = None):
        self.analyzer = analyzer if analyzer is not None else JobAnalyzer()
        self.repository = repository if repository is not None else AnalysisRepository()

    def analyze_job(self, job: Job) -> JobAnalysis:
        analysis = JobAnalysis.model_validate(self.analyzer.analyze(job))
        if analysis.job_id != job.id:
            raise ValueError("Analyzer returned an analysis for a different job")

        return self.repository.save(analysis)

    def get_analysis(self, job_id: UUID) -> JobAnalysis | None:
        return self.repository.get(job_id)


analysis_service = AnalysisService()