from datetime import datetime, timezone 
from uuid import UUID, uuid4 
from app.models.schemas import Job, JobCreate


class JobService:
    def __init__(self):
        self._jobs: dict[UUID, Job] = {}

    def create_job(self, job_data: JobCreate,) -> Job:
        job = Job(
            id=uuid4(),
            created_at=datetime.now(timezone.utc),
            **job_data.model_dump()
        )
        self._jobs[job.id] = job 

        return job 

    def get_job(self, job_id: UUID,) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())

job_service = JobService()