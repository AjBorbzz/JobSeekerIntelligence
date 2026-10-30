from datetime import date

from sqlalchemy import Date, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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