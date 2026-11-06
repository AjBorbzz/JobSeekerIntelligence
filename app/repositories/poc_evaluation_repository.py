import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal
from app.db.models import POCEvaluationRecord, POCProposalRecord
from app.models.poc_evaluation_snapshot import POCEvaluationSnapshot
from app.models.poc_snapshot import POCProposalSnapshot


class POCEvaluationRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def _validate(self, row: POCEvaluationRecord, source: POCProposalRecord) -> POCEvaluationSnapshot:
        proposal = POCProposalSnapshot.model_validate(source)
        snapshot = POCEvaluationSnapshot.model_validate(row)
        if snapshot.evaluation.get("job_id") != str(proposal.job_id):
            raise ValueError("Evaluation belongs to a different job")
        if snapshot.evaluation.get("project_name") != proposal.proposal.get("project_name"):
            raise ValueError("Evaluation belongs to a different project")

        return snapshot

    def add(self, job_id: UUID, proposal_id: int, analysis: BaseModel,
            evaluation: BaseModel) -> POCEvaluationSnapshot:
        analysis_data = analysis.model_dump(mode="json")
        evaluation_data = evaluation.model_dump(mode="json")
        json.dumps((analysis_data, evaluation_data), allow_nan=False)

        with self.session_factory.begin() as session:
            source = session.get(POCProposalRecord, proposal_id)
            if source is None or source.job_id != str(job_id):
                raise ValueError("Saved proposal not found for this job")
            if analysis_data != source.analysis:
                raise ValueError("Evaluation must use the proposal's saved analysis")

            row = POCEvaluationRecord(
                proposal_id=proposal_id, evaluation=evaluation_data,
                saved_at=datetime.now(timezone.utc).isoformat(), schema_version=1,
            )
            session.add(row)
            session.flush()
            snapshot = self._validate(row, source)

        return snapshot

    def get_latest(self, job_id: UUID, proposal_id: int | None = None) -> POCEvaluationSnapshot | None:
        target = proposal_id
        if target is None:
            target = (
                select(POCProposalRecord.id)
                .where(POCProposalRecord.job_id == str(job_id))
                .order_by(POCProposalRecord.id.desc()).limit(1).correlate(None).scalar_subquery()
            )
        statement = (
            select(POCEvaluationRecord, POCProposalRecord)
            .join(POCProposalRecord, POCEvaluationRecord.proposal_id == POCProposalRecord.id)
            .where(POCProposalRecord.job_id == str(job_id), POCEvaluationRecord.proposal_id == target)
            .order_by(POCEvaluationRecord.id.desc()).limit(1)
        )
        with self.session_factory() as session:
            pair = session.execute(statement).first()
            return self._validate(pair[0], pair[1]) if pair is not None else None