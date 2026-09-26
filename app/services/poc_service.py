from uuid import UUID

from app.llm.poc_generator import POCGenerator
from app.models.schemas import (
    Job,
    JobAnalysis,
    POCGenerationRequest,
    POCProposal,
)

from app.services.hybrid_relevance_service import HybridRelevanceService

class POCService:
    def __init__(self,
                 generator: POCGenerator | None = None,
                 relevance_service: HybridRelevanceService | None = None,):
        self.generator = generator or POCGenerator()
        self.relevance_service = relevance_service or HybridRelevanceService()
        self._proposals: dict[UUID, POCProposal] = {}

    def generate(self, job: Job, analysis: JobAnalysis, request: POCGenerationRequest) -> POCProposal:
        relevance = self.relevance_service.calculate(
            criteria=request.criteria,
            job=job,
            analysis=analysis,
        )

        data = self.generator.generator(
            job=job,
            analysis=analysis,
            criteria=request.criteria,
            relevance=relevance,
            max_complexity=request.max_complexity,
        )

        proposal = POCProposal(
            job_id=job.id,
            search_query=request.criteria.query,
            job_relevance_score=relevance.overall_score,
            generated_by=self.generator.client.model,
            **data.model_dump(),
        )

        self._proposals[job.id] = proposal
        return proposal

    def get(self, job_id: UUID) -> POCProposal | None:
        return self._proposals.get(job_id)

poc_service = POCService()