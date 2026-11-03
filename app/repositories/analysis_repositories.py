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
        