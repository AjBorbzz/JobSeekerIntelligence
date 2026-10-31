from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.schemas import JobCreate
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService


def test_job_round_trip(job_sessions):
    service = JobService(JobRepository(job_sessions))
    job = service.create_job(JobCreate(
        title="Python Developer",
        type_of_work="full_time",
        hours_per_week=40,
        date_updated=date(2026, 10, 30),
        job_overview="Build Python APIs using FastAPI and PostgreSQL.",
    ))

    restored = service.get_job(job.id)

    assert restored == job
    assert restored.created_at.utcoffset().total_seconds() == 0
    assert restored.type_of_work.value == "full_time"
    assert restored.date_updated == date(2026, 10, 30)


def test_job_survives_new_engine(job_sessions):
    service = JobService(JobRepository(job_sessions))
    job = service.create_job(JobCreate(
        title="Python Developer",
        job_overview="Build reliable APIs for internal business systems.",
    ))
    with job_sessions() as session:
        previous_engine = session.get_bind()
        database_url = previous_engine.url
    previous_engine.dispose()

    reopened_engine = create_engine(database_url)
    try:
        reopened_sessions = sessionmaker(bind=reopened_engine)
        reopened_service = JobService(JobRepository(reopened_sessions))
        assert reopened_service.get_job(job.id) == job
    finally:
        reopened_engine.dispose()


def test_missing_job_returns_none(job_sessions):
    service = JobService(JobRepository(job_sessions))
    assert service.get_job(uuid4()) is None


def test_list_jobs(job_sessions):
    service = JobService(JobRepository(job_sessions))
    assert service.list_jobs() == []
    job = service.create_job(JobCreate(
        title="Python Developer",
        job_overview="Build reliable APIs for internal business systems.",
    ))
    assert service.list_jobs() == [job]