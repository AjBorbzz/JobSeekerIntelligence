from uuid import UUID 

from app.llm.job_analyzer import JobAnalyzer 
from app.models.schemas import (
    Job, 
    JobAnalysis,
)

class AnalysisService:
    def __init__(self, analyzer: JobAnalyzer | None = None,):
        self.analyzer = analyzer or JobAnalyzer()
        self._analyses: dict[UUID,JobAnalysis,] = {}

    def analyze_job(self,job: Job,) -> JobAnalysis:
        analysis = self.analyzer.analyze(job)
        self._analyses[job.id] = analysis
        return analysis

    def get_analysis(self,job_id: UUID,) -> JobAnalysis | None:
        return self._analyses.get(job_id)


analysis_service = AnalysisService()