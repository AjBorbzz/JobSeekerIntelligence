from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.schemas import JobAnalysis


def test_valid_job_analysis():

    analysis = JobAnalysis(
        job_id=uuid4(),
        role_category="Python Developer",
        role_summary="Backend Python development.",
        seniority="mid",
        required_skills=[
            "Python",
            "FastAPI",
        ],
        preferred_skills=[
            "Docker",
        ],
        tech_stack=[
            "Python",
            "FastAPI",
            "PostgreSQL",
        ],
        responsibilities=[
            "Build APIs",
        ],
        employer_pain_points=[
            "Backend needs modernization",
        ],
        business_problem=(
            "Improve backend application development."
        ),
        expected_deliverables=[
            "REST APIs",
        ],
        evidence=[],
    )

    assert analysis.seniority.value == "mid"

    assert "Python" in analysis.required_skills


def test_invalid_seniority():

    with pytest.raises(ValidationError):

        JobAnalysis(
            job_id=uuid4(),
            role_category="Python Developer",
            role_summary="Backend development.",
            seniority="super_expert",
            required_skills=[],
            preferred_skills=[],
            tech_stack=[],
            responsibilities=[],
            employer_pain_points=[],
            expected_deliverables=[],
            evidence=[],
        )