from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.reports import router
from app.db.database import create_sqlite_engine
from app.db.models import AnalysisRecord, JobRecord, POCEvaluationRecord, POCProposalRecord
from app.models.report import ReportDataError, ReportNotFound, ReportTooLarge
from app.models.schemas import (
    Job, JobAnalysis, POCComplexity, POCEvaluation, POCFeature, POCGenerationRequest,
    POCImplementationStep, POCProposal, POCRequirementEvaluation, POCCoverageStatus, SearchCriteria,
)
from app.reporting.pdf_renderer import render_pdf
from app.repositories.job_repository import JobRepository
from app.repositories.poc_evaluation_repository import POCEvaluationRepository
from app.repositories.poc_proposal_repository import POCProposalRepository
from app.repositories.report_repositories import ReportRepository
from app.services.report_service import ReportService, report_service


def make_job(sessions, **changes):
    values = dict(
        id=uuid4(), created_at=datetime.now(timezone.utc), title="Python Automation Developer",
        company="Example Research Company", job_overview="Build reliable Python automation services and API integrations.",
    )
    job = Job(**(values | changes))
    return JobRepository(sessions).add(job)


def make_analysis(job, summary="Original saved analysis"):
    return JobAnalysis(
        job_id=job.id, role_category="Backend", role_summary=summary,
        required_skills=["Python"], responsibilities=["Build reliable API workflows"],
    )


def save_analysis(sessions, analysis, version=1):
    with sessions.begin() as session:
        session.merge(AnalysisRecord(
            job_id=str(analysis.job_id), payload=analysis.model_dump(mode="json"),
            saved_at=datetime.now(timezone.utc).isoformat(), schema_version=version,
        ))


def save_proposal(sessions, job, name="Workflow Inspector", analysis=None):
    analysis = analysis or make_analysis(job)
    request = POCGenerationRequest(criteria=SearchCriteria(query="Python backend"))
    proposal = POCProposal(
        job_id=job.id, project_name=name, objective="Inspect a small API workflow",
        problem_statement="API failures need clear diagnostics", why_relevant="Shows Python API skills",
        tech_stack=["Python", "FastAPI"],
        features=[POCFeature(name="Inspect", description="Inspect API failures", job_relevance="Backend reliability")],
        implementation_steps=[POCImplementationStep(order=1, title="Build API", description="Validate incoming data")],
        demo_scenario="Submit a sample failing workflow", acceptance_criteria=["A diagnosis is returned"],
        out_of_scope=["Production deployment"], complexity=POCComplexity.SMALL,
        search_query=request.criteria.query, job_relevance_score=83.25, generated_by="fixture-generator",
    )
    saved = POCProposalRepository(sessions).add(job.id, request, analysis, proposal)
    return saved, analysis, proposal


def save_evaluation(sessions, saved, analysis, proposal, summary="Independent fixture evaluation"):
    evaluation = POCEvaluation(
        job_id=analysis.job_id, project_name=proposal.project_name, evaluated_by="fixture-evaluator",
        requirement_coverage_score=75, explicit_skill_coverage_score=100, poc_relevance_score=80,
        matched_required_skills=["Python"], strengths=["Small focused scope"], gaps=["Add a failure case"],
        summary=summary, requirement_evaluations=[POCRequirementEvaluation(
            requirement_id="required_skill:1", status=POCCoverageStatus.COVERED,
            project_evidence=["Python"], explanation="Python is explicitly declared",
        )],
    )
    return POCEvaluationRepository(sessions).add(analysis.job_id, saved.id, analysis, evaluation)


@pytest.fixture
def job(job_sessions):
    return make_job(job_sessions)


@pytest.fixture
def repository(job_sessions):
    return ReportRepository(job_sessions)


def pdf_text(data):
    reader = PdfReader(BytesIO(data))
    return reader, "\n".join(page.extract_text() for page in reader.pages)


def test_job_only_snapshot_marks_missing_sections(job, repository):
    result = repository.load(job.id)
    assert result.job == job
    assert result.analysis_origin == "missing"
    assert result.proposal is None and result.evaluation is None


def test_latest_saved_analysis_is_used_only_without_a_proposal(job, repository, job_sessions):
    analysis = make_analysis(job)
    save_analysis(job_sessions, analysis)
    result = repository.load(job.id)
    assert result.analysis == analysis
    assert result.analysis_origin == "latest_saved_analysis"
    assert isinstance(result.latest_analysis_saved_at, datetime)


def test_missing_job_is_not_a_partial_report(repository):
    with pytest.raises(ReportNotFound):
        repository.load(uuid4())


def test_proposal_pins_analysis_not_the_later_reanalysis(job, repository, job_sessions):
    saved, old, proposal = save_proposal(job_sessions, job)
    save_analysis(job_sessions, make_analysis(job, "Later analysis must not replace the pinned input"))
    result = repository.load(job.id)
    assert result.analysis == old
    assert result.analysis_origin == "proposal_snapshot"
    assert result.proposal_id == saved.id
    assert result.request.criteria.query == proposal.search_query


def test_unevaluated_new_proposal_never_reuses_old_evaluation(job, repository, job_sessions):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    save_evaluation(job_sessions, saved, analysis, proposal)
    newer, _, _ = save_proposal(job_sessions, job, name="New proposal")
    result = repository.load(job.id)
    assert result.proposal_id == newer.id
    assert result.evaluation is None


def test_explicit_old_proposal_uses_its_own_evaluation(job, repository, job_sessions):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    evaluation = save_evaluation(job_sessions, saved, analysis, proposal)
    save_proposal(job_sessions, job, name="New proposal")
    result = repository.load(job.id, saved.id)
    assert result.proposal_id == saved.id
    assert result.evaluation_id == evaluation.id
    assert result.evaluation.project_name == proposal.project_name


def test_newest_evaluation_is_selected_within_the_pinned_proposal(job, repository, job_sessions):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    save_evaluation(job_sessions, saved, analysis, proposal, summary="Older evaluation")
    latest = save_evaluation(job_sessions, saved, analysis, proposal, summary="Newer evaluation")
    result = repository.load(job.id)
    assert result.evaluation_id == latest.id
    assert result.evaluation.summary == "Newer evaluation"


def test_wrong_job_cannot_select_another_jobs_proposal(job, repository, job_sessions):
    other = make_job(job_sessions)
    saved, _, _ = save_proposal(job_sessions, other)
    with pytest.raises(ReportNotFound):
        repository.load(job.id, saved.id)


@pytest.mark.parametrize("kind", ["proposal", "evaluation", "analysis"])
def test_unsupported_storage_version_is_rejected(job, repository, job_sessions, kind):
    if kind == "analysis":
        save_analysis(job_sessions, make_analysis(job), version=2)
    else:
        saved, analysis, proposal = save_proposal(job_sessions, job)
        evaluation = save_evaluation(job_sessions, saved, analysis, proposal)
        with job_sessions.begin() as session:
            model, key = (POCProposalRecord, saved.id) if kind == "proposal" else (POCEvaluationRecord, evaluation.id)
            session.get(model, key).schema_version = 2
    with pytest.raises(ReportDataError):
        repository.load(job.id)


@pytest.mark.parametrize("field,value", [
    ("job_id", str(uuid4())), ("project_name", "Wrong project"), ("poc_relevance_score", 1000),
])
def test_corrupt_evaluation_is_not_printed_as_valid(job, repository, job_sessions, field, value):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    evaluation = save_evaluation(job_sessions, saved, analysis, proposal)
    with job_sessions.begin() as session:
        row = session.get(POCEvaluationRecord, evaluation.id)
        row.evaluation = row.evaluation | {field: value}
    with pytest.raises(ReportDataError):
        repository.load(job.id)


def test_conflicting_saved_query_is_rejected(job, repository, job_sessions):
    saved, _, _ = save_proposal(job_sessions, job)
    with job_sessions.begin() as session:
        row = session.get(POCProposalRecord, saved.id)
        row.proposal = row.proposal | {"search_query": "Unrelated criteria"}
    with pytest.raises(ReportDataError):
        repository.load(job.id)


def test_corrupt_latest_analysis_id_is_rejected(job, repository, job_sessions):
    analysis = make_analysis(job).model_copy(update={"job_id": uuid4()})
    with job_sessions.begin() as session:
        session.add(AnalysisRecord(
            job_id=str(job.id), payload=analysis.model_dump(mode="json"),
            saved_at=datetime.now(timezone.utc).isoformat(), schema_version=1,
        ))
    with pytest.raises(ReportDataError):
        repository.load(job.id)


def test_reads_use_explicit_snapshot_and_make_no_writes(job, repository, job_sessions):
    statements = []
    engine = job_sessions.kw["bind"]
    def observed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())
    event.listen(engine, "before_cursor_execute", observed)
    try:
        repository.load(job.id)
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert "BEGIN" in statements
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP")) for sql in statements)


def test_concurrent_new_proposal_does_not_mix_the_read_snapshot(job, repository, job_sessions):
    first, _, _ = save_proposal(job_sessions, job)
    engine = job_sessions.kw["bind"]
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    triggered = []
    def publish(connection, cursor, statement, parameters, context, executemany):
        if not triggered and statement.lstrip().upper().startswith("SELECT JOBS."):
            triggered.append(True)
            save_proposal(job_sessions, job, name="Published after the first read")
    event.listen(engine, "after_cursor_execute", publish)
    try:
        result = repository.load(job.id)
    finally:
        event.remove(engine, "after_cursor_execute", publish)
    assert triggered
    assert result.proposal_id == first.id


def test_snapshot_survives_a_fresh_engine(job, repository, job_sessions):
    saved, _, _ = save_proposal(job_sessions, job)
    engine = job_sessions.kw["bind"]
    path = Path(engine.url.database)
    engine.dispose()
    reopened = create_sqlite_engine(path)
    try:
        restored = ReportRepository(sessionmaker(bind=reopened)).load(job.id)
        assert restored.proposal_id == saved.id
        assert restored.job.id == job.id
    finally:
        reopened.dispose()


def test_input_size_limit_returns_no_truncated_report(job, repository, job_sessions, monkeypatch):
    from app.repositories import report_repositories as module
    monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 10)
    with pytest.raises(ReportTooLarge):
        repository.load(job.id)


def test_complete_pdf_contains_saved_sections_and_scores(job, repository, job_sessions):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    save_evaluation(job_sessions, saved, analysis, proposal)
    data = render_pdf(repository.load(job.id))
    reader, text = pdf_text(data)
    assert data.startswith(b"%PDF-")
    assert len(reader.pages) >= 2
    for expected in ["Workflow Inspector", "Original saved analysis", "Independent fixture evaluation", "83.25", "80.00"]:
        assert expected in text
    assert "Provenance and limitations" in text


def test_partial_pdf_explains_missing_sections(job, repository):
    _, text = pdf_text(render_pdf(repository.load(job.id)))
    assert "No saved analysis." in text
    assert "No saved proposal." in text
    assert "No proposal selected; no evaluation attached." in text


def test_untrusted_markup_and_urls_remain_inert(job_sessions):
    job = make_job(job_sessions, job_overview='Text <img src="https://untrusted.example/image"> and <b>literal markup</b> must not execute.')
    reader, text = pdf_text(render_pdf(ReportRepository(job_sessions).load(job.id)))
    assert '<img src="https://untrusted.example/image">' in text
    assert "<b>literal markup</b>" in text
    assert not any(page.get("/Annots") for page in reader.pages)
    assert "/OpenAction" not in reader.trailer["/Root"]


def test_font_policy_is_explicit_without_missing_glyph_boxes(job_sessions):
    job = make_job(job_sessions, job_overview="Personal notes: salary ₱50,000, café work, and emoji 😀 are display test data.")
    _, text = pdf_text(render_pdf(ReportRepository(job_sessions).load(job.id)))
    assert "PHP 50,000" in text
    assert "café" in text
    assert "[U+1F600]" in text


def test_long_source_wraps_and_preserves_the_tail(job_sessions):
    overview = ("Long source paragraph about reliable Python APIs. " * 500) + " FINAL_SOURCE_TAIL"
    job = make_job(job_sessions, job_overview=overview)
    reader, text = pdf_text(render_pdf(ReportRepository(job_sessions).load(job.id)))
    assert len(reader.pages) >= 5
    assert "FINAL_SOURCE_TAIL" in text


@pytest.mark.parametrize("limit_name,limit", [("MAX_PAGES", 1), ("MAX_PDF_BYTES", 20)])
def test_pdf_output_limits_are_enforced(job, repository, monkeypatch, limit_name, limit):
    from app.reporting import pdf_renderer as module
    monkeypatch.setattr(module, limit_name, limit)
    with pytest.raises(ReportTooLarge):
        render_pdf(repository.load(job.id))


@pytest.fixture
def api(job_sessions, monkeypatch):
    monkeypatch.setattr(report_service, "repository", ReportRepository(job_sessions))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_api_download_has_safe_headers(api, job):
    response = api.get(f"/jobs/{job.id}/report.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith('attachment; filename="job-intelligence-')


@pytest.mark.parametrize("path,expected", [
    ("/jobs/not-a-uuid/report.pdf", 422),
    (f"/jobs/{uuid4()}/report.pdf", 404),
])
def test_api_invalid_or_missing_job(api, path, expected):
    assert api.get(path).status_code == expected


def test_api_rejects_nonpositive_proposal_id(api, job):
    assert api.get(f"/jobs/{job.id}/report.pdf?proposal_id=0").status_code == 422


def test_api_rejects_unknown_proposal_version(api, job):
    assert api.get(f"/jobs/{job.id}/report.pdf?proposal_id=999999").status_code == 404


def test_api_corrupt_record_is_conflict_without_raw_payload(api, job, job_sessions):
    save_analysis(job_sessions, make_analysis(job), version=2)
    response = api.get(f"/jobs/{job.id}/report.pdf")
    assert response.status_code == 409
    assert "Original saved analysis" not in response.text


def test_api_size_error_is_distinct(api, job, monkeypatch):
    from app.repositories import report_repositories as module
    monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 10)
    assert api.get(f"/jobs/{job.id}/report.pdf").status_code == 413


def test_database_failure_is_not_reported_as_missing(api, job, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("Internal storage failure")
    monkeypatch.setattr(report_service.repository, "load", broken)
    response = api.get(f"/jobs/{job.id}/report.pdf")
    assert response.status_code == 500


def test_export_with_network_forbidden(job, job_sessions, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Report export attempted a network call")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    data, filename = ReportService(ReportRepository(job_sessions)).export(job.id)
    assert data.startswith(b"%PDF-")
    assert str(job.id) in filename


def test_export_does_not_change_saved_record_counts(job, job_sessions):
    saved, analysis, proposal = save_proposal(job_sessions, job)
    save_evaluation(job_sessions, saved, analysis, proposal)
    def counts():
        with job_sessions() as session:
            return tuple(session.scalar(select(func.count()).select_from(model)) for model in (
                JobRecord, AnalysisRecord, POCProposalRecord, POCEvaluationRecord,
            ))
    before = counts()
    ReportService(ReportRepository(job_sessions)).export(job.id)
    assert counts() == before