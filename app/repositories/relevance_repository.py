import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal
from app.db.models import RelevanceRunRecord
from app.models.relevance_history import RelevanceKind, RelevanceRun


class RelevanceRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def add(self, job_id: UUID, kind: RelevanceKind, criteria: BaseModel, result: BaseModel) -> RelevanceRun:
        criteria_data = criteria.model_dump(mode="json")
        result_data = result.model_dump(mode="json")
        json.dumps((criteria_data, result_data), allow_nan=False)

        if "job_id" in result_data and result_data["job_id"] != str(job_id):
            raise ValueError("Relevance result belongs to a different job")

        row = RelevanceRunRecord(
            job_id=str(job_id), kind=kind, criteria=criteria_data, result=result_data,
            saved_at=datetime.now(timezone.utc).isoformat(), schema_version=1,
        )
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            saved = RelevanceRun.model_validate(row)

        return saved

    def list_for_job(self, job_id: UUID, kind: RelevanceKind | None = None,
                     limit: int = 20, before_id: int | None = None) -> list[RelevanceRun]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if before_id is not None and before_id < 1:
            raise ValueError("before_id must be positive")

        statement = select(RelevanceRunRecord).where(RelevanceRunRecord.job_id == str(job_id))
        if kind is not None:
            statement = statement.where(RelevanceRunRecord.kind == kind)
        if before_id is not None:
            statement = statement.where(RelevanceRunRecord.id < before_id)
        statement = statement.order_by(RelevanceRunRecord.id.desc()).limit(limit)

        with self.session_factory() as session:
            return [RelevanceRun.model_validate(row) for row in session.scalars(statement)]


relevance_repository = RelevanceRepository()