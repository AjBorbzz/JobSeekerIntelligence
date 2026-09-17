from uuid import UUID 
from fastapi import APIRouter, HTTPException, status 
from app.models.schemas import JobCreate, Job
from app.services.job_service import job_service


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