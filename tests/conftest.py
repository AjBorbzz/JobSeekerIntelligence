import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.repositories.job_repository import JobRepository
from app.services.job_service import job_service


@pytest.fixture
def job_sessions(tmp_path):
    test_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def isolate_job_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(job_service, "repository", JobRepository(job_sessions))