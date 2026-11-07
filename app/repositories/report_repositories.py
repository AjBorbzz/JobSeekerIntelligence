import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import SessionLocal
from app.db.models import AnalysisRecord, JobRecord, POCEvaluationRecord, POCProposalRecord
from app.models.poc_evaluation_snapshot import POCEvaluationSnapshot
from app.models.poc_snapshot import POCProposalSnapshot
from app.models.report import ReportDataError, ReportNotFound, ReportSnapshot, ReportTooLarge
from app.models.schemas import Job, JobAnalysis, POCEvaluation, POCGenerationRequest, POCProposal

MAX_SNAPSHOT_BYTES = 500_000


class ReportRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def load(self, job_id: UUID, proposal_id: int | None = None) -> ReportSnapshot:
        if proposal_id is not None and proposal_id < 1:
            raise ValueError("proposal_id must be positive")
        try:
            with self.session_factory() as session:
                # Explicit BEGIN also establishes a snapshot under SQLite legacy transaction mode.
                session.connection().exec_driver_sql("BEGIN")
                row = session.get(JobRecord, str(job_id))
                if row is None:
                    raise ReportNotFound("Job not found")
                report = ReportSnapshot(
                    generated_at=datetime.now(timezone.utc),
                    job=Job.model_validate(row, from_attributes=True),
                )
                statement = select(POCProposalRecord).where(POCProposalRecord.job_id == str(job_id))
                if proposal_id is not None:
                    statement = statement.where(POCProposalRecord.id == proposal_id)
                source = session.scalar(statement.order_by(POCProposalRecord.id.desc()).limit(1))
                if source is None and proposal_id is not None:
                    raise ReportNotFound("Proposal version not found for this job")
                if source is None:
                    analysis_row = session.get(AnalysisRecord, str(job_id))
                    if analysis_row is not None:
                        if analysis_row.schema_version != 1:
                            raise ReportDataError("Unsupported analysis storage version")
                        report.analysis = JobAnalysis.model_validate(analysis_row.payload)
                        if report.analysis.job_id != job_id:
                            raise ReportDataError("Analysis belongs to a different job")
                        report.analysis_origin = "latest_saved_analysis"
                        report.latest_analysis_saved_at = datetime.fromisoformat(analysis_row.saved_at)
                else:
                    saved = POCProposalSnapshot.model_validate(source)
                    report.request = POCGenerationRequest.model_validate(saved.request)
                    report.analysis = JobAnalysis.model_validate(saved.analysis)
                    report.proposal = POCProposal.model_validate(saved.proposal)
                    if report.proposal.search_query != report.request.criteria.query:
                        raise ReportDataError("Proposal and saved search query do not match")
                    report.analysis_origin = "proposal_snapshot"
                    report.proposal_id = saved.id
                    report.proposal_saved_at = saved.saved_at
                    evaluation_row = session.scalar(
                        select(POCEvaluationRecord)
                        .where(POCEvaluationRecord.proposal_id == saved.id)
                        .order_by(POCEvaluationRecord.id.desc()).limit(1)
                    )
                    if evaluation_row is not None:
                        evaluation = POCEvaluationSnapshot.model_validate(evaluation_row)
                        report.evaluation = POCEvaluation.model_validate(evaluation.evaluation)
                        if (report.evaluation.job_id != job_id or
                                report.evaluation.project_name != report.proposal.project_name):
                            raise ReportDataError("Evaluation does not match the selected proposal")
                        report.evaluation_id = evaluation.id
                        report.evaluation_saved_at = evaluation.saved_at
                # Read session closes before layout/rendering; no database writes occur.
            encoded = json.dumps(report.model_dump(mode="json"), allow_nan=False).encode("utf-8")
            if len(encoded) > MAX_SNAPSHOT_BYTES:
                raise ReportTooLarge("Report data exceeds the configured input limit")
            return report
        except ReportTooLarge:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise ReportDataError("Stored report data is invalid or incompatible") from exc