import pytest
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, create_sqlite_engine
from app.repositories.analysis_repositories import AnalysisRepository
from app.repositories.job_repository import JobRepository
from app.services.analysis_service import analysis_service
from app.services.job_service import job_service

from app.repositories.relevance_repository import relevance_repository

from app.repositories.poc_proposal_repository import POCProposalRepository
from app.services.poc_service import poc_service

from app.repositories.poc_evaluation_repository import POCEvaluationRepository
from app.services.poc_evaluation_service import poc_evaluation_service

from app.repositories.external_job_repository import ExternalJobRepository
from app.services.greenhouse_service import greenhouse_service

@pytest.fixture
def job_sessions(tmp_path):
    test_engine = create_sqlite_engine(tmp_path / "jobs.db")
    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        test_engine.dispose()


@pytest.fixture(autouse=True)
def isolate_job_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(job_service, "repository", JobRepository(job_sessions))


@pytest.fixture(autouse=True)
def isolate_analysis_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(analysis_service, "repository", AnalysisRepository(job_sessions))

@pytest.fixture(autouse=True)
def isolate_relevance_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(relevance_repository, "session_factory", job_sessions)

@pytest.fixture(autouse=True)
def isolate_poc_proposal_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(poc_service, "repository", POCProposalRepository(job_sessions))

@pytest.fixture(autouse=True)
def isolate_poc_evaluation_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(poc_evaluation_service, "repository", POCEvaluationRepository(job_sessions))

@pytest.fixture(autouse=True)
def isolate_external_job_storage(job_sessions, monkeypatch):
    monkeypatch.setattr(greenhouse_service, "repository", ExternalJobRepository(job_sessions))