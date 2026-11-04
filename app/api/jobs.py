from uuid import UUID 
from fastapi import APIRouter, HTTPException, status, Query
from app.models.schemas import (
    JobCreate, 
    Job,
    JobAnalysis,
    JobCreate,
    SemanticRelevance,
    SemanticRelevanceRequest,
    HybridRelevance, 
    SearchCriteria
)

from app.services.job_service import job_service
from app.services.analysis_service import analysis_service
from app.services.relevance_service import (
    relevance_service,
)

from app.services.hybrid_relevance_service import hybrid_relevance_service

from app.models.schemas import POCGenerationRequest, POCProposal
from app.services.poc_service import poc_service

from app.models.relevance_history import RelevanceKind, RelevanceRun
from app.repositories.relevance_repository import relevance_repository

router = APIRouter(prefix="/jobs", tags=["jobs"],)

@router.post("/manual", response_model=Job, status_code=status.HTTP_201_CREATED,)
def create_manual_job(job_data: JobCreate,) -> Job:
    return job_service.create_job(job_data)

@router.get("", response_model=list[Job],)
def list_jobs() -> list[Job]:
    return job_service.list_jobs() 

@router.get("/{job_id}", response_model=Job,)
def get_job(job_id: UUID,) -> Job:
    job = job_service.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Job not Found.")
    return job

@router.post("/{job_id}/analyze", response_model=JobAnalysis,)
def analyze_job(job_id: UUID,) -> JobAnalysis:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    return analysis_service.analyze_job(job)


@router.get("/{job_id}/analysis", response_model=JobAnalysis,)
def get_job_analysis(job_id: UUID,) -> JobAnalysis:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found.")
    analysis = analysis_service.get_analysis(job_id)

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job has not been analyzed.")

    return analysis


@router.post("/{job_id}/semantic-relevance", response_model=SemanticRelevance,)
def calculate_semantic_relevance(job_id: UUID, request: SemanticRelevanceRequest,) -> SemanticRelevance:
    job = job_service.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    analysis = analysis_service.get_analysis(job_id)

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job must be analyzed before semantic relevance can be calculated.")

    result = relevance_service.calculate_semantic_relevance(request.query, job, analysis)
    relevance_repository.add(job_id, "semantic", request, SemanticRelevance.model_validate(result))
    return result


@router.post("/{job_id}/relevance", response_model=HybridRelevance)
def calculate_job_relevance(job_id: UUID, criteria: SearchCriteria) -> HybridRelevance:
    job = job_service.get_job(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    analysis = analysis_service.get_analysis(job_id)

    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job must be analyzed before relevance can be calculated",
        )

    result = hybrid_relevance_service.calculate(criteria, job, analysis)
    relevance_repository.add(job_id, "hybrid", criteria, HybridRelevance.model_validate(result))
    return result


@router.post("/{job_id}/poc", response_model=POCProposal)
def generate_poc(job_id: UUID, request: POCGenerationRequest) -> POCProposal:
    job = job_service.get_job(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    analysis = analysis_service.get_analysis(job_id)

    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job must be analyzed before a POC can be generated",
        )

    return poc_service.generate(
        job=job,
        analysis=analysis,
        request=request,
    )


@router.get("/{job_id}/poc", response_model=POCProposal)
def get_poc(job_id: UUID) -> POCProposal:
    job = job_service.get_job(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    proposal = poc_service.get(job_id)

    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POC has not been generated",
        )

    return proposal

@router.get("/{job_id}/relevance-history", response_model=list[RelevanceRun])
def get_relevance_history(
    job_id: UUID, kind: RelevanceKind | None = None,
    limit: int = Query(20, ge=1, le=100), before_id: int | None = Query(None, ge=1),
) -> list[RelevanceRun]:
    if job_service.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return relevance_repository.list_for_job(job_id, kind=kind, limit=limit, before_id=before_id)