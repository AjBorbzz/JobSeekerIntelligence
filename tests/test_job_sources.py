import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.job_imports import router
from app.models.job_import import HtmlJobImportRequest
from app.models.schemas import WorkType
from app.repositories.job_repository import JobRepository
from app.services.job_import_service import JobImportService, job_import_service
from app.services.job_service import JobService
from app.sources.base import JobSourceError
from app.sources.html_sources import ExampleHtmlJobSource, JsonLdJobSource, clean_text

FIXTURES = Path(__file__).parent / "fixtures"


def posting(**updates):
    node = {
        "@type": "JobPosting", "title": "Python Developer",
        "description": "<p>Build reliable Python APIs using FastAPI and PostgreSQL.</p>",
        "hiringOrganization": {"name": "Example Company"}, "employmentType": "FULL_TIME",
    }
    return {**node, **updates}


def html_for(document):
    payload = json.dumps(document).replace("</", "<\\/")
    return f'<html><script type="application/ld+json">{payload}</script></html>'


def test_jsonld_fixture_maps_supported_fields():
    parsed = JsonLdJobSource().parse((FIXTURES / "jsonld_job.html").read_text())
    assert parsed.data.title == "Python Backend Developer"
    assert parsed.data.company == "Example Company"
    assert parsed.data.type_of_work == WorkType.FULL_TIME
    assert parsed.data.source_url == "https://example.com/jobs/python-backend"
    assert "Integrate external services." in parsed.data.job_overview
    assert parsed.data.salary is None
    assert parsed.data.date_updated is None
    assert any("datePosted" in text for text in parsed.warnings)


def test_example_html_fixture_is_a_distinct_adapter():
    html = (FIXTURES / "example_job.html").read_text()
    parsed = ExampleHtmlJobSource().parse(html, "https://example.com/jobs/python")
    assert parsed.data.title == "Python Backend Developer"
    assert parsed.data.company == "Example Company"
    assert parsed.data.type_of_work == WorkType.FULL_TIME
    assert parsed.data.source_url == "https://example.com/jobs/python"


@pytest.mark.parametrize("document", [
    {"@graph": [posting()]}, [posting()], {"mainEntity": posting()},
    {"@graph": [{"mainEntity": [posting()]}]},
])
def test_common_jsonld_containers(document):
    assert JsonLdJobSource().parse(html_for(document)).data.title == "Python Developer"


@pytest.mark.parametrize("type_name", ["https://schema.org/JobPosting", ["Thing", "JobPosting"]])
def test_supported_type_forms(type_name):
    assert JsonLdJobSource().parse(html_for(posting(**{"@type": type_name}))).data.title == "Python Developer"


def test_multiple_jobs_require_explicit_selection():
    html = html_for([posting(), posting(title="Go Developer")])
    with pytest.raises(JobSourceError, match="job_index"):
        JsonLdJobSource().parse(html)
    assert JsonLdJobSource().parse(html, job_index=1).data.title == "Go Developer"


@pytest.mark.parametrize("index", [-1, 2])
def test_source_rejects_out_of_range_index(index):
    with pytest.raises(JobSourceError, match="outside"):
        JsonLdJobSource().parse(html_for(posting()), job_index=index)


def test_malformed_companion_block_is_reported():
    html = '<script type="application/ld+json">{bad}</script>' + html_for(posting())
    parsed = JsonLdJobSource().parse(html)
    assert any("malformed" in warning for warning in parsed.warnings)


def test_jsonld_is_not_silently_replaced_with_page_title():
    with pytest.raises(JobSourceError, match="No readable"):
        JsonLdJobSource().parse("<html><title>Careers</title><p>No structured job data here.</p></html>")


@pytest.mark.parametrize("updates", [
    {"title": ""}, {"title": {"name": "Python"}}, {"description": "short"},
])
def test_invalid_job_facts_are_rejected(updates):
    with pytest.raises(JobSourceError, match="validation"):
        JsonLdJobSource().parse(html_for(posting(**updates)))


@pytest.mark.parametrize("label,expected", [
    ("PART_TIME", WorkType.PART_TIME), ("CONTRACTOR", WorkType.CONTRACT),
    ("freelance", WorkType.FREELANCE), (["FULL_TIME", "PART_TIME"], WorkType.UNKNOWN),
    ("INTERNSHIP", WorkType.UNKNOWN),
])
def test_employment_mapping_is_conservative(label, expected):
    assert JsonLdJobSource().parse(html_for(posting(employmentType=label))).data.type_of_work == expected


def test_no_salary_hours_or_date_are_inferred():
    parsed = JsonLdJobSource().parse(html_for(posting(
        baseSalary={"currency": "USD", "value": 90000}, workHours="40",
        datePosted="2026-11-06", dateModified="2026-11-06",
    )))
    assert parsed.data.salary is None
    assert parsed.data.hours_per_week is None
    assert parsed.data.date_updated is None
    assert len(parsed.warnings) == 4


def test_visible_text_discards_noncontent_markup():
    text = clean_text('<div>Build <b>Python APIs</b>.</div><script>secret()</script><span hidden>hidden</span>')
    assert "Python APIs" in text
    assert "secret" not in text
    assert "hidden" not in text
    assert "<" not in text


def test_source_url_is_metadata_and_overrides_structured_url():
    parsed = JsonLdJobSource().parse(html_for(posting(url="https://other.example/job")), "http://localhost:11434/meta")
    assert parsed.data.source_url == "http://localhost:11434/meta"


def test_unsafe_structured_url_is_not_stored():
    parsed = JsonLdJobSource().parse(html_for(posting(url="javascript:alert(1)")))
    assert parsed.data.source_url is None
    assert parsed.warnings


def test_example_adapter_rejects_ambiguous_title():
    html = (FIXTURES / "example_job.html").read_text() + "<h1 data-job-title>Another title</h1>"
    with pytest.raises(JobSourceError, match="exactly one"):
        ExampleHtmlJobSource().parse(html)


def test_example_adapter_does_not_accept_job_index():
    with pytest.raises(JobSourceError, match="only supported"):
        ExampleHtmlJobSource().parse((FIXTURES / "example_job.html").read_text(), job_index=0)


def test_nonfinite_json_is_not_accepted():
    html = '<script type="application/ld+json">{"@type":"JobPosting","bad":NaN}</script>'
    with pytest.raises(JobSourceError, match="No readable"):
        JsonLdJobSource().parse(html)


def test_json_graph_node_limit():
    document = {"@graph": [{} for _ in range(5001)]}
    with pytest.raises(JobSourceError, match="too many"):
        JsonLdJobSource().parse(html_for(document))


def test_import_persists_via_existing_job_service(job_sessions):
    jobs = JobService(JobRepository(job_sessions))
    importer = JobImportService(jobs=jobs)
    request = HtmlJobImportRequest(html=html_for(posting()))
    first = importer.import_html(request)
    second = importer.import_html(request)
    assert first.job.id != second.job.id
    assert jobs.get_job(first.job.id) == first.job
    assert len(jobs.list_jobs()) == 2


@pytest.fixture
def import_api(job_sessions, monkeypatch):
    jobs = JobService(JobRepository(job_sessions))
    monkeypatch.setattr(job_import_service, "jobs", jobs)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False), jobs


def test_api_creates_job_without_network_or_llm(import_api, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("No network connection is permitted in this test")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    client, jobs = import_api
    response = client.post("/jobs/from-html", json={
        "html": html_for(posting()), "source_url": "http://localhost:11434/meta",
    })
    assert response.status_code == 201
    result = response.json()
    assert result["parser"] == "jsonld"
    job_id = UUID(result["job"]["id"])
    assert jobs.get_job(job_id).title == "Python Developer"
    assert jobs.get_job(job_id).created_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("changes", [
    {"parser": "unknown"}, {"source_url": "file:///etc/passwd"},
    {"source_url": "https://user:password@example.com/job"}, {"job_index": -1},
    {"html": "x" * 500001}, {"html": "short"},
])
def test_api_rejects_invalid_requests_before_storage(import_api, changes):
    client, jobs = import_api
    response = client.post("/jobs/from-html", json={"html": html_for(posting()), **changes})
    assert response.status_code == 422
    assert jobs.list_jobs() == []


def test_api_reports_parse_error_without_creating_job(import_api):
    client, jobs = import_api
    response = client.post("/jobs/from-html", json={"html": "<html><p>No job description here.</p></html>"})
    assert response.status_code == 422
    assert jobs.list_jobs() == []


def test_api_supports_explicit_example_adapter(import_api):
    client, _ = import_api
    response = client.post("/jobs/from-html", json={
        "html": (FIXTURES / "example_job.html").read_text(), "parser": "example_html",
    })
    assert response.status_code == 201


def test_api_keeps_database_errors_distinct(import_api, monkeypatch):
    client, jobs = import_api

    def fail(_):
        raise RuntimeError("Simulated storage failure")

    monkeypatch.setattr(jobs, "create_job", fail)
    response = client.post("/jobs/from-html", json={"html": html_for(posting())})
    assert response.status_code == 500


def test_imported_job_survives_a_fresh_database_engine(job_sessions):
    from sqlalchemy.orm import sessionmaker
    from app.db.database import create_sqlite_engine

    importer = JobImportService(jobs=JobService(JobRepository(job_sessions)))
    saved = importer.import_html(HtmlJobImportRequest(html=html_for(posting()))).job
    with job_sessions() as session:
        old = session.get_bind()
        path = Path(old.url.database)
    old.dispose()
    reopened = create_sqlite_engine(path)
    try:
        restored = JobService(JobRepository(sessionmaker(bind=reopened))).get_job(saved.id)
        assert restored == saved
    finally:
        reopened.dispose()


def test_source_interface_accepts_an_injected_adapter(job_sessions):
    from app.models.schemas import JobCreate
    from app.sources.base import ParsedJob

    class FixedSource:
        def parse(self, html, source_url=None, job_index=None):
            return ParsedJob(JobCreate(
                title="Injected Source Job",
                job_overview="Build reliable backend services for internal reporting.",
            ), ["Adapter-specific note."])

    importer = JobImportService(
        jobs=JobService(JobRepository(job_sessions)), sources={"jsonld": FixedSource()},
    )
    result = importer.import_html(HtmlJobImportRequest(html="<html>Controlled adapter input</html>"))
    assert result.job.title == "Injected Source Job"
    assert result.warnings == ["Adapter-specific note."]