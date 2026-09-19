from uuid import UUID 
from fastapi import APIRouter, HTTPException, status 
from app.models.schemas import (
    JobCreate, 
    Job,
    JobAnalysis,
    JobCreate,
    SemanticRelevance,
    SemanticRelevanceRequest,
)

from app.services.job_service import job_service
from app.services.analysis_service import analysis_service
from app.services.relevance_service import (
    relevance_service,
)

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

    return relevance_service.calculate_semantic_relevance(query=request.query, job=job, analysis=analysis,)