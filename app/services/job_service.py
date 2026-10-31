from datetime import datetime, timezone 
from uuid import UUID, uuid4 
from app.models.schemas import Job, JobCreate
from app.repositories.job_repository import JobRepository


class JobService:
    def __init__(self, repository : JobRepository| None = None):
        self.repository = repository if repository is not None else JobRepository()

    def create_job(self, job_data: JobCreate,) -> Job:
        job = Job(
            id=uuid4(),
            created_at=datetime.now(timezone.utc),
            **job_data.model_dump()
        )
        return self.repository.add(job)

    def get_job(self, job_id: UUID,) -> Job | None:
        return self.repository.get(job_id)

    def list_jobs(self) -> list[Job]:
        return self.repository.list()

job_service = JobService()