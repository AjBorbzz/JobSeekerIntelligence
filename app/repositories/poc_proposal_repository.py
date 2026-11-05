import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal
from app.db.models import POCProposalRecord
from app.models.poc_snapshot import POCProposalSnapshot


class POCProposalRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def add(self, job_id: UUID, request: BaseModel, analysis: BaseModel, proposal: BaseModel) -> POCProposalSnapshot:
        payloads = {
            "request": request.model_dump(mode="json"),
            "analysis": analysis.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        }
        json.dumps(payloads, allow_nan=False)
        row = POCProposalRecord(
            job_id=str(job_id), **payloads,
            saved_at=datetime.now(timezone.utc).isoformat(), schema_version=1,
        )
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            saved = POCProposalSnapshot.model_validate(row)

        return saved

    def get_latest(self, job_id: UUID) -> POCProposalSnapshot | None:
        statement = (
            select(POCProposalRecord)
            .where(POCProposalRecord.job_id == str(job_id))
            .order_by(POCProposalRecord.id.desc())
            .limit(1)
        )
        with self.session_factory() as session:
            row = session.scalar(statement)
            return POCProposalSnapshot.model_validate(row) if row is not None else None

    def get_version(self, job_id: UUID, proposal_id: int) -> POCProposalSnapshot | None:
        with self.session_factory() as session:
            row = session.get(POCProposalRecord, proposal_id)
            if row is None or row.job_id != str(job_id):
                return None

            return POCProposalSnapshot.model_validate(row)