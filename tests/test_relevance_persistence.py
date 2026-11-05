from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.database import create_sqlite_engine
from app.models.schemas import JobCreate
from app.repositories.job_repository import JobRepository
from app.repositories.relevance_repository import RelevanceRepository
from app.services.job_service import JobService


class CriteriaFixture(BaseModel):
    query: str = "Python backend developer"
    required_skills: list[str] = ["Python"]
    weights: dict[str, float] = {"semantic": 0.5, "role": 0.2, "skills": 0.2, "constraints": 0.1}


class ResultFixture(BaseModel):
    job_id: UUID
    overall_score: float = 81.25
    components: dict[str, float] = {"semantic": 82.0, "skills": 100.0}
    explanation: str | None = None


def create_job(job_sessions, title="Python Developer"):
    service = JobService(JobRepository(job_sessions))
    return service.create_job(JobCreate(
        title=title, job_overview="Build backend services with Python and PostgreSQL.",
    ))


@pytest.fixture
def scoring_input(job_sessions):
    job = create_job(job_sessions)
    return job.id, CriteriaFixture(), ResultFixture(job_id=job.id)


def test_relevance_snapshot_round_trip(job_sessions, scoring_input):
    job_id, criteria, result = scoring_input
    repository = RelevanceRepository(job_sessions)
    saved = repository.add(job_id, "hybrid", criteria, result)

    assert saved.criteria == criteria.model_dump(mode="json")
    assert saved.result == result.model_dump(mode="json")
    assert saved.saved_at.utcoffset() == timezone.utc.utcoffset(None)
    assert repository.list_for_job(job_id) == [saved]


def test_repeated_scoring_appends_and_can_page(job_sessions, scoring_input):
    job_id, criteria, result = scoring_input
    repository = RelevanceRepository(job_sessions)
    first = repository.add(job_id, "hybrid", criteria, result)
    second = repository.add(job_id, "hybrid", criteria, result)

    assert second.id > first.id
    assert repository.list_for_job(job_id, limit=1) == [second]
    assert repository.list_for_job(job_id, limit=1, before_id=second.id) == [first]


def test_history_filters_by_job_and_kind(job_sessions, scoring_input):
    job_id, criteria, result = scoring_input
    repository = RelevanceRepository(job_sessions)
    semantic = repository.add(job_id, "semantic", criteria, result)
    hybrid = repository.add(job_id, "hybrid", criteria, result)
    other = create_job(job_sessions, "Another Developer")
    repository.add(other.id, "hybrid", criteria, ResultFixture(job_id=other.id))

    assert repository.list_for_job(job_id, kind="semantic") == [semantic]
    assert repository.list_for_job(job_id) == [hybrid, semantic]
    assert repository.list_for_job(uuid4()) == []


def test_relevance_survives_new_engine(job_sessions, scoring_input):
    job_id, criteria, result = scoring_input
    saved = RelevanceRepository(job_sessions).add(job_id, "hybrid", criteria, result)
    with job_sessions() as session:
        old_engine = session.get_bind()
        database_path = Path(old_engine.url.database)
    old_engine.dispose()

    reopened = create_sqlite_engine(database_path)
    try:
        assert RelevanceRepository(sessionmaker(bind=reopened)).list_for_job(job_id) == [saved]
    finally:
        reopened.dispose()


def test_orphan_write_rolls_back(job_sessions, scoring_input):
    job_id, criteria, result = scoring_input
    repository = RelevanceRepository(job_sessions)
    missing_id = uuid4()
    with pytest.raises(IntegrityError):
        repository.add(missing_id, "hybrid", criteria, ResultFixture(job_id=missing_id))

    assert repository.list_for_job(missing_id) == []
    assert repository.add(job_id, "hybrid", criteria, result).job_id == job_id


def test_wrong_result_job_id_is_rejected(job_sessions, scoring_input):
    job_id, criteria, _ = scoring_input
    repository = RelevanceRepository(job_sessions)
    with pytest.raises(ValueError, match="different job"):
        repository.add(job_id, "hybrid", criteria, ResultFixture(job_id=uuid4()))

    assert repository.list_for_job(job_id) == []


def test_non_finite_scores_are_rejected(job_sessions, scoring_input):
    job_id, criteria, _ = scoring_input
    repository = RelevanceRepository(job_sessions)
    with pytest.raises(ValueError):
        repository.add(job_id, "hybrid", criteria, ResultFixture(job_id=job_id, overall_score=float("nan")))

    assert repository.list_for_job(job_id) == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"before_id": 0}])
def test_history_rejects_out_of_range_paging(job_sessions, scoring_input, kwargs):
    job_id, _, _ = scoring_input
    with pytest.raises(ValueError):
        RelevanceRepository(job_sessions).list_for_job(job_id, **kwargs)