from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_job():
    payload = {
        "title": "Python Developer",
        "source_url": "https://example.com/job/123",
        "company": "Example Company",
        "type_of_work": "full_time",
        "hours_per_week": 40,
        "salary": "$2000/month",
        "date_updated": "2026-09-17",
        "job_overview": (
            "We need a Python developer experienced with "
            "FastAPI, PostgreSQL, APIs, and backend systems."
        ),
    }

    response = client.post(
        "/jobs/manual",
        json=payload,
    )

    assert response.status_code == 201

    data = response.json()

    assert data["title"] == "Python Developer"
    assert data["hours_per_week"] == 40
    assert "id" in data
    assert "created_at" in data


def test_invalid_hours():
    payload = {
        "title": "Python Developer",
        "hours_per_week": 200,
        "job_overview": (
            "A sufficiently long job description "
            "used specifically for validation testing."
        ),
    }

    response = client.post(
        "/jobs/manual",
        json=payload,
    )

    assert response.status_code == 422