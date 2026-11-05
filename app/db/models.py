from datetime import date

from sqlalchemy import Date, Float, String, Text, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON, ForeignKey, Integer

from app.db.database import Base


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(String(200))
    type_of_work: Mapped[str] = mapped_column(String(20))
    hours_per_week: Mapped[float | None] = mapped_column(Float)
    salary: Mapped[str | None] = mapped_column(Text)
    date_updated: Mapped[date | None] = mapped_column(Date)
    job_overview: Mapped[str] = mapped_column(Text)


class AnalysisRecord(Base):
    __tablename__ = "job_analyses"

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="RESTRICT"), primary_key=True,
    )
    payload: Mapped[dict] = mapped_column(JSON)
    saved_at: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class RelevanceRunRecord(Base):
    __tablename__ = "relevance_runs"
    __table_args__ = (
        CheckConstraint("kind IN ('semantic', 'hybrid')", name="ck_relevance_runs_kind"),
        Index("ix_relevance_runs_job_id_id", "job_id", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(8))
    criteria: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    saved_at: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)

class POCProposalRecord(Base):
    __tablename__ = "poc_proposals"
    __table_args__ = (
        Index("ix_poc_proposals_job_id_id", "job_id", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="RESTRICT"))
    request: Mapped[dict] = mapped_column(JSON)
    analysis: Mapped[dict] = mapped_column(JSON)
    proposal: Mapped[dict] = mapped_column(JSON)
    saved_at: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)