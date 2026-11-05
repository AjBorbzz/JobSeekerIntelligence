from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.database import create_sqlite_engine
from app.db.models import POCProposalRecord
from app.models.schemas import JobCreate
from app.repositories.job_repository import JobRepository
from app.repositories.poc_proposal_repository import POCProposalRepository
from app.services.job_service import JobService


class RequestFixture(BaseModel):
    criteria: dict[str, str] = {"query": "Python backend developer"}
    max_complexity: str = "small"


class AnalysisFixture(BaseModel):
    job_id: UUID
    evidence: list[str] = ["Build Python APIs"]


class ProposalFixture(BaseModel):
    job_id: UUID
    project_name: str = "Backend API — café demo"
    job_relevance_score: float = 82.5


def make_job(job_sessions):
    service = JobService(JobRepository(job_sessions))
    return service.create_job(JobCreate(
        title="Python Developer", job_overview="Build reliable backend APIs using FastAPI.",
    ))


@pytest.fixture
def inputs(job_sessions):
    job = make_job(job_sessions)
    return job.id, RequestFixture(), AnalysisFixture(job_id=job.id), ProposalFixture(job_id=job.id)


def test_proposal_and_inputs_round_trip(job_sessions, inputs):
    job_id, request, analysis, proposal = inputs
    repository = POCProposalRepository(job_sessions)
    saved = repository.add(job_id, request, analysis, proposal)

    assert saved.request == request.model_dump(mode="json")
    assert saved.analysis == analysis.model_dump(mode="json")
    assert saved.proposal == proposal.model_dump(mode="json")
    assert saved.saved_at.utcoffset() == timezone.utc.utcoffset(None)
    assert repository.get_latest(job_id) == saved


def test_regeneration_keeps_the_old_version(job_sessions, inputs):
    job_id, request, analysis, proposal = inputs
    repository = POCProposalRepository(job_sessions)
    first = repository.add(job_id, request, analysis, proposal)
    revised = proposal.model_copy(update={"project_name": "Second proposal"})
    second = repository.add(job_id, request, analysis, revised)

    assert second.id > first.id
    assert repository.get_latest(job_id) == second
    assert repository.get_version(job_id, first.id) == first


def test_proposal_reads_are_scoped_to_job(job_sessions, inputs):
    repository = POCProposalRepository(job_sessions)
    saved = repository.add(*inputs)
    other_job = make_job(job_sessions)

    assert repository.get_latest(other_job.id) is None
    assert repository.get_version(other_job.id, saved.id) is None
    assert repository.get_version(saved.job_id, saved.id + 1) is None


def test_proposal_survives_new_engine(job_sessions, inputs):
    saved = POCProposalRepository(job_sessions).add(*inputs)
    with job_sessions() as session:
        old_engine = session.get_bind()
        path = Path(old_engine.url.database)
    old_engine.dispose()

    reopened = create_sqlite_engine(path)
    try:
        repository = POCProposalRepository(sessionmaker(bind=reopened))
        assert repository.get_latest(saved.job_id) == saved
        assert repository.get_version(saved.job_id, saved.id) == saved
    finally:
        reopened.dispose()


def test_orphan_proposal_is_rejected(job_sessions):
    job_id = uuid4()
    repository = POCProposalRepository(job_sessions)
    with pytest.raises(IntegrityError):
        repository.add(job_id, RequestFixture(), AnalysisFixture(job_id=job_id), ProposalFixture(job_id=job_id))

    assert repository.get_latest(job_id) is None


@pytest.mark.parametrize("bad_field", ["analysis", "proposal"])
def test_mismatched_ids_do_not_replace_last_good_proposal(job_sessions, inputs, bad_field):
    job_id, request, analysis, proposal = inputs
    repository = POCProposalRepository(job_sessions)
    saved = repository.add(*inputs)
    if bad_field == "analysis":
        analysis = analysis.model_copy(update={"job_id": uuid4()})
    else:
        proposal = proposal.model_copy(update={"job_id": uuid4()})

    with pytest.raises(ValidationError, match="different job"):
        repository.add(job_id, request, analysis, proposal)

    assert repository.get_latest(job_id) == saved


def test_unsupported_snapshot_version_is_not_returned(job_sessions, inputs):
    repository = POCProposalRepository(job_sessions)
    saved = repository.add(*inputs)
    with job_sessions.begin() as session:
        session.get(POCProposalRecord, saved.id).schema_version = 2

    with pytest.raises(ValidationError):
        repository.get_latest(saved.job_id)


def test_invalid_json_number_is_not_saved(job_sessions, inputs):
    job_id, request, analysis, proposal = inputs
    repository = POCProposalRepository(job_sessions)
    invalid = proposal.model_copy(update={"job_relevance_score": float("inf")})

    with pytest.raises(ValueError):
        repository.add(job_id, request, analysis, invalid)

    assert repository.get_latest(job_id) is None