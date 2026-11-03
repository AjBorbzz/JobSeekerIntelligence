from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, create_sqlite_engine
from app.db.models import AnalysisRecord
from app.models.schemas import JobAnalysis, JobCreate
from app.repositories.analysis_repositories import AnalysisRepository
from app.repositories.job_repository import JobRepository
from app.services.analysis_service import AnalysisService
from app.services.job_service import JobService


class FakeAnalyzer:
    def __init__(self, result: JobAnalysis):
        self.result = result
        self.calls = 0

    def analyze(self, job):
        self.calls += 1
        return self.result.model_copy(deep=True)


class FailingAnalyzer:
    def analyze(self, job):
        raise RuntimeError("Simulated inference failure")


@pytest.fixture
def stored_job(job_sessions):
    service = JobService(JobRepository(job_sessions))
    return service.create_job(JobCreate(
        title="Python Developer",
        job_overview="Build Python APIs using FastAPI and PostgreSQL.",
    ))


@pytest.fixture
def analysis(stored_job):
    return JobAnalysis(
        job_id=stored_job.id,
        role_category="Backend Development",
        role_summary="Build Python APIs — café demo.",
        seniority="unknown",
        required_skills=["Python", "FastAPI"],
        preferred_skills=[],
        tech_stack=["Python", "FastAPI", "PostgreSQL"],
        responsibilities=["Build Python APIs"],
        employer_pain_points=[],
        business_problem=None,
        expected_deliverables=["Python APIs"],
        evidence=[{
            "category": "required_skill",
            "claim": "Python development",
            "source_text": "Build Python APIs",
        }],
    )


def test_analysis_round_trip(job_sessions, analysis):
    repository = AnalysisRepository(job_sessions)
    repository.save(analysis)
    restored = repository.get(analysis.job_id)
    assert restored == analysis
    assert restored.evidence[0].source_text == "Build Python APIs"
    assert restored.business_problem is None

    with job_sessions() as session:
        record = session.get(AnalysisRecord, str(analysis.job_id))
        assert isinstance(record.payload, dict)
        assert record.payload["job_id"] == str(analysis.job_id)
        assert record.schema_version == 1
        assert datetime.fromisoformat(record.saved_at).utcoffset().total_seconds() == 0


def test_missing_analysis_returns_none(job_sessions):
    assert AnalysisRepository(job_sessions).get(uuid4()) is None


def test_reanalysis_updates_one_row(job_sessions, analysis):
    repository = AnalysisRepository(job_sessions)
    repository.save(analysis)
    revised = analysis.model_copy(update={"role_summary": "Updated analysis."})
    repository.save(revised)

    assert repository.get(analysis.job_id) == revised
    with job_sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRecord)) == 1


def test_analysis_survives_new_engine(job_sessions, analysis):
    AnalysisRepository(job_sessions).save(analysis)
    with job_sessions() as session:
        old_engine = session.get_bind()
        database_path = old_engine.url.database
    old_engine.dispose()

    reopened_engine = create_sqlite_engine(Path(database_path))
    try:
        sessions = sessionmaker(bind=reopened_engine)
        service = AnalysisService(analyzer=FailingAnalyzer(), repository=AnalysisRepository(sessions))
        assert service.get_analysis(analysis.job_id) == analysis
    finally:
        reopened_engine.dispose()


def test_foreign_key_rejects_orphan_and_session_factory_recovers(job_sessions, analysis):
    repository = AnalysisRepository(job_sessions)
    orphan = analysis.model_copy(update={"job_id": uuid4()})
    with pytest.raises(IntegrityError):
        repository.save(orphan)

    assert repository.get(orphan.job_id) is None
    repository.save(analysis)
    assert repository.get(analysis.job_id) == analysis


def test_service_saves_fake_analysis(job_sessions, stored_job, analysis):
    fake = FakeAnalyzer(analysis)
    service = AnalysisService(analyzer=fake, repository=AnalysisRepository(job_sessions))

    assert service.analyze_job(stored_job) == analysis
    assert service.get_analysis(stored_job.id) == analysis
    assert fake.calls == 1


def test_service_rejects_wrong_job_id(job_sessions, stored_job, analysis):
    wrong = analysis.model_copy(update={"job_id": uuid4()})
    service = AnalysisService(analyzer=FakeAnalyzer(wrong), repository=AnalysisRepository(job_sessions))

    with pytest.raises(ValueError, match="different job"):
        service.analyze_job(stored_job)

    assert service.get_analysis(stored_job.id) is None


def test_inference_failure_preserves_previous_analysis(job_sessions, stored_job, analysis):
    repository = AnalysisRepository(job_sessions)
    repository.save(analysis)
    service = AnalysisService(analyzer=FailingAnalyzer(), repository=repository)

    with pytest.raises(RuntimeError, match="Simulated inference failure"):
        service.analyze_job(stored_job)

    assert repository.get(stored_job.id) == analysis


def test_create_all_preserves_existing_job(job_sessions, stored_job):
    with job_sessions() as session:
        engine = session.get_bind()
    Base.metadata.create_all(engine)
    assert JobRepository(job_sessions).get(stored_job.id) == stored_job


def test_payload_job_id_mismatch_is_rejected(job_sessions, analysis):
    repository = AnalysisRepository(job_sessions)
    repository.save(analysis)
    with job_sessions.begin() as session:
        record = session.get(AnalysisRecord, str(analysis.job_id))
        record.payload = {**record.payload, "job_id": str(uuid4())}

    with pytest.raises(ValueError, match="database key"):
        repository.get(analysis.job_id)


def test_unknown_schema_version_is_rejected(job_sessions, analysis):
    repository = AnalysisRepository(job_sessions)
    repository.save(analysis)
    with job_sessions.begin() as session:
        record = session.get(AnalysisRecord, str(analysis.job_id))
        record.schema_version = 999

    with pytest.raises(ValueError, match="schema version"):
        repository.get(analysis.job_id)


def test_additive_initialization_keeps_phase8a_job(tmp_path):
    from app.db.models import JobRecord

    engine = create_sqlite_engine(tmp_path / "upgrade.db")
    try:
        JobRecord.__table__.create(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        service = JobService(JobRepository(sessions))
        job = service.create_job(JobCreate(
            title="Existing Phase 8A Job",
            job_overview="A previously stored Python backend development job.",
        ))

        Base.metadata.create_all(engine)

        assert service.get_job(job.id) == job
        analysis = JobAnalysis(
            job_id=job.id,
            role_category="Backend Development",
            role_summary="Analyze a job retained from Phase 8A.",
        )
        AnalysisRepository(sessions).save(analysis)
        assert AnalysisRepository(sessions).get(job.id) == analysis
    finally:
        engine.dispose()