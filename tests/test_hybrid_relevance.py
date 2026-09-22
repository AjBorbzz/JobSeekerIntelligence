from datetime import datetime, timezone
from uuid import uuid4

from app.models.schemas import Job, JobAnalysis, SearchCriteria
from app.scoring.hybrid_relevance import (
    constraint_score,
    role_match_score,
    skill_match_score,
    weighted_score,
)


def create_test_job():
    job_id = uuid4()

    job = Job(
        id=job_id,
        created_at=datetime.now(timezone.utc),
        title="Python AI Backend Developer",
        source_url=None,
        company="Example",
        type_of_work="full_time",
        hours_per_week=40,
        salary=None,
        date_updated=None,
        job_overview="Python backend development using FastAPI and PostgreSQL.",
    )

    analysis = JobAnalysis(
        job_id=job_id,
        role_category="Backend Developer",
        role_summary="Python backend development for an AI platform.",
        seniority="unknown",
        required_skills=["Python", "FastAPI"],
        preferred_skills=["RAG"],
        tech_stack=["Python", "FastAPI", "PostgreSQL"],
        responsibilities=["Build backend APIs"],
        employer_pain_points=[],
        business_problem=None,
        expected_deliverables=[],
        evidence=[],
    )

    return job, analysis


def test_role_match():
    job, analysis = create_test_job()

    score, details = role_match_score(
        "Python backend developer",
        job,
        analysis,
    )

    assert score == 100.0
    assert details


def test_skill_match():
    _, analysis = create_test_job()

    criteria = SearchCriteria(
        query="Python developer",
        required_skills=["Python", "FastAPI"],
        preferred_skills=["PostgreSQL"],
    )

    score, details = skill_match_score(criteria, analysis)

    assert score == 100.0
    assert "python" in details["matched_required"]
    assert "fastapi" in details["matched_required"]
    assert "postgresql" in details["matched_preferred"]


def test_missing_skill():
    _, analysis = create_test_job()

    criteria = SearchCriteria(
        query="Python developer",
        required_skills=["Python", "Django"],
    )

    score, details = skill_match_score(criteria, analysis)

    assert score == 50.0
    assert "python" in details["matched_required"]
    assert "django" in details["missing_required"]


def test_work_constraints():
    job, _ = create_test_job()

    criteria = SearchCriteria(
        query="Python developer",
        work_types=["full_time"],
        max_hours_per_week=40,
    )

    score, notes = constraint_score(criteria, job)

    assert score == 100.0
    assert notes


def test_weighted_score():
    score = weighted_score([
        (80.0, 0.50),
        (100.0, 0.20),
    ])

    assert score == 85.71