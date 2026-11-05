from uuid import UUID

from app.llm.poc_generator import POCGenerator
from app.models.schemas import (
    Job,
    JobAnalysis,
    POCGenerationRequest,
    POCProposal,
)

from app.services.hybrid_relevance_service import HybridRelevanceService
from app.repositories.poc_proposal_repository import POCProposalRepository

class POCService:
    def __init__(self, generator: POCGenerator | None = None,
                    relevance_service: HybridRelevanceService | None = None,
                    repository: POCProposalRepository | None = None,
                ):
        self.generator = generator if generator is not None else POCGenerator()
        self.relevance_service = relevance_service if relevance_service is not None else HybridRelevanceService()
        self.repository = repository if repository is not None else POCProposalRepository()

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

        self.repository.add(job.id, request, analysis, proposal)
        return proposal

    def get(self, job_id: UUID) -> POCProposal | None:
        snapshot = self.repository.get_latest(job_id)
        return POCProposal.model_validate(snapshot.proposal) if snapshot is not None else None

poc_service = POCService()

