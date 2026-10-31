
from uuid import UUID 

from sqlalchemy import select 
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal 
from app.db.models import JobRecord
from app.models.schemas import Job 


class JobRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def add(self, job: Job) -> Job:
        values = job.model_dump()
        values.update(
            id=str(job.id),
            created_at=job.created_at.isoformat(),
            type_of_work=job.type_of_work.values,
        )

        with self.session_factory.begin() as session:
            session.add(JobRecord(**values))

        return job

    def get(self,job_id: UUID) -> Job | None:
        with self.session_factory() as session:
            record = session.get(JobRecord, str(job_id))
            return Job.model_validate(record, from_attributes=True) if record is not None else None

    def list(self) -> list[Job]:
        with self.session_factory() as session:
            records = session.scalars(select(JobRecord).order_by(JobRecord.created_at, JobRecord.id))
            return [Job.model_validate(record, from_attributes=True) for record in records]