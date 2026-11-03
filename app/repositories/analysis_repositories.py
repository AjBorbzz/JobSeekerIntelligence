from datetime import datetime, timezone 
from uuid import UUID 

from sqlalchemy.dialects.sqlite import insert 
from sqlalchemy.orm import Session, sessionmaker 

from app.db.database import SessionLocal 
from app.db.models import AnalysisRecord 
from app.models.schemas import JobAnalysis 


class AnalysisRepository:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal):
        self.session_factory = session_factory

    def save(self, analysis: JobAnalysis) -> JobAnalysis:
        statement = insert(AnalysisRecord).values(
            job_id = str(analysis.job_id),
            payload = analysis.model_dump(mode="json"),
            saved_at = datetime.now(timezone.utc).isoformat(),
            schema_version=1,
        )

        statement = statement.on_conflict_do_update(
            index_elements=[AnalysisRecord.job_id],
            set={
                "payload": statement.excluded.payload,
                "saved_at": statement.excluded.saved_at,
                "schema_version": statement.excluded.schema_version,
            },
        )

        with self.session_factory.begin() as session:
            session.execute(statement)

        return analysis

    def get(self, job_id: UUID) -> JobAnalysis | None:
        with self.session_factory() as session:
            record = session.get(AnalysisRecord, str(job_id))
            if record is None:
                return None
            if record.schema_version != 1:
                raise ValueError("Unsupported stored analysis schema version")

            analysis = JobAnalysis.model_validate(record.payload)
            if analysis.job_id != job_id:
                raise ValueError("Stored analysis job_id does not match its database key")

            return analysis
        