from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.database import create_sqlite_engine
from app.db.models import POCEvaluationRecord
from app.models.schemas import JobCreate
from app.repositories.job_repository import JobRepository
from app.repositories.poc_evaluation_repository import POCEvaluationRepository
from app.repositories.poc_proposal_repository import POCProposalRepository
from app.services.job_service import JobService


class RequestFixture(BaseModel):
    criteria: dict[str, str] = {"query": "Python Developer"}


class AnalysisFixture(BaseModel):
    job_id: UUID
    required_skills: list[str] = ["Python"]


class ProposalFixture(BaseModel):
    job_id: UUID
    project_name: str = "Python API"


class EvaluationFixture(BaseModel):
    job_id: UUID
    project_name: str = "Python API"
    poc_relevance_score: float = 80.0
    gaps: list[str] = []
    summary: str = "Useful API — café demo."


def make_job(job_sessions):
    return JobService(JobRepository(job_sessions)).create_job(JobCreate(
        title="Python Developer", job_overview="Build Python APIs with FastAPI and PostgreSQL.",
    ))


@pytest.fixture
def inputs(job_sessions):
    job = make_job(job_sessions)
    analysis = AnalysisFixture(job_id=job.id)
    snapshot = POCProposalRepository(job_sessions).add(
        job.id, RequestFixture(), analysis, ProposalFixture(job_id=job.id),
    )
    return job.id, snapshot, analysis, EvaluationFixture(job_id=job.id)


def save(repository, inputs):
    job_id, proposal, analysis, evaluation = inputs
    return repository.add(job_id, proposal.id, analysis, evaluation)


def test_evaluation_round_trip(job_sessions, inputs):
    job_id, proposal, _, evaluation = inputs
    repository = POCEvaluationRepository(job_sessions)
    stored = save(repository, inputs)
    assert stored.proposal_id == proposal.id
    assert stored.evaluation == evaluation.model_dump(mode="json")
    assert stored.saved_at.utcoffset() == timezone.utc.utcoffset(None)
    assert repository.get_latest(job_id) == stored


def test_repeat_evaluation_preserves_previous_run(job_sessions, inputs):
    repository = POCEvaluationRepository(job_sessions)
    first = save(repository, inputs)
    second = save(repository, inputs)
    assert second.id > first.id
    assert repository.get_latest(inputs[0]) == second
    with job_sessions() as session:
        assert session.get(POCEvaluationRecord, first.id) is not None


def test_regeneration_does_not_return_an_old_evaluation(job_sessions, inputs):
    job_id, old, analysis, _ = inputs
    repository = POCEvaluationRepository(job_sessions)
    saved = save(repository, inputs)
    POCProposalRepository(job_sessions).add(
        job_id, RequestFixture(), analysis, ProposalFixture(job_id=job_id),
    )
    assert repository.get_latest(job_id) is None
    assert repository.get_latest(job_id, old.id) == saved


def test_finished_evaluation_stays_with_selected_old_version(job_sessions, inputs):
    job_id, old, analysis, evaluation = inputs
    new = POCProposalRepository(job_sessions).add(
        job_id, RequestFixture(), analysis, ProposalFixture(job_id=job_id),
    )
    repository = POCEvaluationRepository(job_sessions)
    stored = repository.add(job_id, old.id, analysis, evaluation)
    assert repository.get_latest(job_id) is None
    assert repository.get_latest(job_id, old.id) == stored
    assert repository.get_latest(job_id, new.id) is None


def test_wrong_job_cannot_read_or_attach(job_sessions, inputs):
    repository = POCEvaluationRepository(job_sessions)
    save(repository, inputs)
    other = make_job(job_sessions)
    _, proposal, analysis, evaluation = inputs
    assert repository.get_latest(other.id, proposal.id) is None
    with pytest.raises(ValueError, match="not found"):
        repository.add(other.id, proposal.id, analysis, evaluation)


def test_changed_analysis_is_rejected(job_sessions, inputs):
    repository = POCEvaluationRepository(job_sessions)
    first = save(repository, inputs)
    job_id, proposal, analysis, evaluation = inputs
    changed = analysis.model_copy(update={"required_skills": ["Go"]})
    with pytest.raises(ValueError, match="saved analysis"):
        repository.add(job_id, proposal.id, changed, evaluation)
    assert repository.get_latest(job_id) == first


@pytest.mark.parametrize("changes", [{"job_id": uuid4()}, {"project_name": "Wrong project"}])
def test_mismatched_result_rolls_back(job_sessions, inputs, changes):
    repository = POCEvaluationRepository(job_sessions)
    first = save(repository, inputs)
    job_id, proposal, analysis, evaluation = inputs
    invalid = evaluation.model_copy(update=changes)
    with pytest.raises(ValueError, match="different"):
        repository.add(job_id, proposal.id, analysis, invalid)
    assert repository.get_latest(job_id) == first


def test_missing_proposal_is_rejected(job_sessions, inputs):
    job_id, _, analysis, evaluation = inputs
    repository = POCEvaluationRepository(job_sessions)
    with pytest.raises(ValueError, match="not found"):
        repository.add(job_id, 999999, analysis, evaluation)
    assert repository.get_latest(job_id) is None


def test_database_rejects_an_orphan_even_without_repository(job_sessions):
    with pytest.raises(IntegrityError):
        with job_sessions.begin() as session:
            session.add(POCEvaluationRecord(
                proposal_id=999999, evaluation={}, saved_at="2026-11-06T00:00:00+00:00", schema_version=1,
            ))


def test_retrieval_survives_new_engine(job_sessions, inputs):
    stored = save(POCEvaluationRepository(job_sessions), inputs)
    with job_sessions() as session:
        old = session.get_bind()
        path = Path(old.url.database)
    old.dispose()

    reopened = create_sqlite_engine(path)
    try:
        repository = POCEvaluationRepository(sessionmaker(bind=reopened))
        assert repository.get_latest(inputs[0]) == stored
    finally:
        reopened.dispose()


def test_unsupported_storage_version_is_rejected(job_sessions, inputs):
    repository = POCEvaluationRepository(job_sessions)
    stored = save(repository, inputs)
    with job_sessions.begin() as session:
        session.get(POCEvaluationRecord, stored.id).schema_version = 2

    with pytest.raises(ValidationError):
        repository.get_latest(inputs[0])


def test_nonfinite_score_is_not_saved(job_sessions, inputs):
    job_id, proposal, analysis, evaluation = inputs
    repository = POCEvaluationRepository(job_sessions)
    invalid = evaluation.model_copy(update={"poc_relevance_score": float("nan")})
    with pytest.raises(ValueError):
        repository.add(job_id, proposal.id, analysis, invalid)
    assert repository.get_latest(job_id) is None