from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal
from app.db.models import ExternalJobIdentity, JobRecord
from app.models.schemas import Job, JobCreate

PROVIDER = "greenhouse"


class ExternalJobRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def _read(self, session: Session, identity: ExternalJobIdentity) -> Job:
        row = session.get(JobRecord, identity.job_id)
        if row is None:
            raise RuntimeError("External job identity has no parent job")
        return Job.model_validate(row, from_attributes=True)

    def find(self, board_token: str, external_id: int) -> Job | None:
        with self.session_factory() as session:
            identity = session.get(ExternalJobIdentity, (PROVIDER, board_token, str(external_id)))
            return self._read(session, identity) if identity is not None else None

    def import_once(self, board_token: str, external_id: int, data: JobCreate) -> tuple[Job, bool]:
        try:
            with self.session_factory.begin() as session:
                identity = session.get(ExternalJobIdentity, (PROVIDER, board_token, str(external_id)))
                if identity is not None:
                    return self._read(session, identity), False
                job = Job(id=uuid4(), created_at=datetime.now(timezone.utc), **data.model_dump())
                values = job.model_dump()
                values.update(id=str(job.id), created_at=job.created_at.isoformat(), type_of_work=job.type_of_work.value)
                session.add(JobRecord(**values))
                session.flush()
                session.add(ExternalJobIdentity(
                    provider=PROVIDER, board_token=board_token, external_id=str(external_id), job_id=str(job.id),
                ))
            return job, True
        except IntegrityError:
            existing = self.find(board_token, external_id)
            if existing is not None:
                return existing, False
            raise