from dataclasses import replace
from datetime import timezone
from uuid import UUID

import pytest

from app.evaluation import capture_baseline as runner
from app.evaluation.dataset import load_dataset, requirement_keys
from app.evaluation.score_run import dataset_fingerprint, load_predictions, score_run
from app.models.schemas import (
    HybridRelevance, JobAnalysis, POCEvaluationData, POCRequirement, POCRequirementEvaluation,
)


@pytest.fixture
def dataset():
    return load_dataset()


@pytest.fixture
def components():
    def analyze(job):
        return JobAnalysis(job_id=job.id, role_category="test", role_summary="Fake extraction")

    def rank(criteria, job, analysis):
        return HybridRelevance(job_id=job.id, query=criteria.query, overall_score=50, components=[])

    def requirements(analysis):
        return [
            POCRequirement(id=f"requirement-{index}", requirement_type=kind, text=text)
            for index, (kind, text) in enumerate(sorted(requirement_keys(analysis)), 1)
        ]

    def evaluate(requirements, proposal):
        return POCEvaluationData(
            summary="Fake POC evaluation",
            requirement_evaluations=[
                POCRequirementEvaluation(requirement_id=row.id, status="missing", explanation="Fake result")
                for row in reversed(requirements)
            ],
        )

    def validate(requirements, proposal, assessment):
        assert proposal.project_name
        assert assessment.summary

    return runner.Components(analyze, rank, requirements, evaluate, validate)


def test_capture_isolates_stages_and_skips_holdout(dataset, components):
    group = next(group for group in dataset.groups if group.split == "dev")
    source_by_id = {runner.synthetic_job(dataset.dataset_id, case).id: case for case in group.cases}
    called = {"analyze": [], "rank": [], "evaluate": [], "validate": []}

    def analyze(job):
        case = source_by_id[job.id]
        assert job.job_overview == case.job.job_overview
        assert "analysis_gold" not in job.model_dump()
        called["analyze"].append(job.id)
        job.title = "Mutation in fake analyzer"
        return components.analyze(job)

    def rank(criteria, job, analysis):
        case = source_by_id[job.id]
        assert job.title == case.job.title
        assert analysis.required_skills == case.analysis_gold.required_skills
        assert criteria == group.criteria
        called["rank"].append(job.id)
        criteria.query = "Mutation in fake ranker"
        analysis.required_skills.clear()
        return components.rank(group.criteria, job, analysis)

    def evaluate(requirements, proposal):
        case = source_by_id[proposal.job_id]
        assert proposal.project_name == case.poc.proposal.project_name
        assert proposal.search_query == group.criteria.query
        assert proposal.job_relevance_score == 0
        assert {(item.requirement_type, item.text) for item in requirements} == requirement_keys(case.analysis_gold)
        called["evaluate"].append(proposal.job_id)
        return components.evaluate(requirements, proposal)

    def validate(requirements, proposal, assessment):
        called["validate"].append(proposal.job_id)
        components.validate_assessment(requirements, proposal, assessment)

    fingerprint = dataset_fingerprint(dataset)
    run = runner.capture(dataset, "test-run", replace(
        components, analyze=analyze, rank=rank, evaluate=evaluate, validate_assessment=validate,
    ))
    assert run.split == "dev"
    assert run.source == "observed"  # The injected fakes in this test are not a baseline.
    assert set(run.cases) == {case.id for case in group.cases}
    assert set(called["analyze"]) == set(called["rank"]) == set(source_by_id)
    assert len(called["analyze"]) == len(called["rank"]) == 4
    assert len(called["evaluate"]) == len(called["validate"]) == 1
    assert dataset_fingerprint(dataset) == fingerprint
    report = score_run(dataset, run)
    assert report["complete"]
    assert report["poc"]["correct"] == 1  # Fake statuses were scored, not copied from gold.


def test_synthetic_job_identity_is_stable_and_distinct(dataset):
    cases = dataset.groups[0].cases
    first = runner.synthetic_job(dataset.dataset_id, cases[0])
    assert first.id == runner.synthetic_job(dataset.dataset_id, cases[0]).id
    assert first.id != runner.synthetic_job(dataset.dataset_id, cases[1]).id
    assert first.created_at.tzinfo == timezone.utc


def test_stage_exception_isolated_without_leaking_error_text(dataset, components, capsys):
    def fail(job):
        raise RuntimeError("Do not print raw output")

    run = runner.capture(dataset, "test-run", replace(components, analyze=fail))
    report = score_run(dataset, run)
    assert report["complete"] is False
    assert report["extraction"]["available_cases"] == 0
    assert report["ranking"]["python-backend"]["complete"]
    assert report["poc"]["complete"]
    assert run.metadata["failure.dev-01.extraction"] == "RuntimeError"
    assert "Do not print raw output" not in capsys.readouterr().err
    assert "Do not print raw output" not in run.model_dump_json()


def test_reject_wrong_extraction_job(dataset, components):
    def analyze(job):
        return components.analyze(job).model_copy(update={"job_id": UUID(int=0)})

    run = runner.capture(dataset, "test-run", replace(components, analyze=analyze))
    assert all(row.analysis is None for row in run.cases.values())


@pytest.mark.parametrize("field,value", [("job_id", UUID(int=0)), ("query", "wrong query")])
def test_reject_wrong_relevance_identity(dataset, components, field, value):
    def rank(criteria, job, analysis):
        return components.rank(criteria, job, analysis).model_copy(update={field: value})

    run = runner.capture(dataset, "test-run", replace(components, rank=rank))
    assert all(row.relevance_score is None for row in run.cases.values())


@pytest.mark.parametrize("change", ["missing", "unknown", "duplicate"])
def test_reject_unmapped_poc_ids(dataset, components, change):
    def evaluate(requirements, proposal):
        result = components.evaluate(requirements, proposal)
        rows = result.requirement_evaluations
        if change == "missing":
            rows.pop()
        elif change == "unknown":
            rows[0].requirement_id = "unknown-id"
        else:
            rows.append(rows[0])
        return result

    run = runner.capture(dataset, "test-run", replace(components, evaluate=evaluate))
    assert run.cases["dev-01"].coverage is None
    assert not score_run(dataset, run)["poc"]["complete"]


def test_validator_failure_invalidates_poc_stage(dataset, components):
    def validate(*args):
        raise ValueError("Rejected evidence")

    run = runner.capture(dataset, "test-run", replace(components, validate_assessment=validate))
    assert run.cases["dev-01"].coverage is None


def test_requirement_contract_drift_stops_before_poc_inference(dataset, components):
    def unexpected(analysis):
        return components.build_requirements(analysis)[:-1]

    def evaluate(*args):
        pytest.fail("The POC evaluator must not run with the wrong requirement set")

    run = runner.capture(dataset, "test-run", replace(
        components, build_requirements=unexpected, evaluate=evaluate,
    ))
    assert run.cases["dev-01"].coverage is None


def test_predictions_round_trip_and_refuse_overwrite(tmp_path, dataset, components):
    path = tmp_path / "predictions.json"
    run = runner.capture(dataset, "test-run", components)
    runner.save_predictions(path, run)
    before = path.read_bytes()
    assert load_predictions(path) == run
    with pytest.raises(FileExistsError):
        runner.save_predictions(path, run)
    assert path.read_bytes() == before


def test_ranker_target_is_explicit_callable():
    assert runner.resolve_ranker("app.evaluation.score_run:score_run") is score_run
    with pytest.raises(ValueError, match="module:attribute"):
        runner.resolve_ranker("not-a-target")
    with pytest.raises(ValueError, match="not callable"):
        runner.resolve_ranker("app.evaluation.score_run:FIELDS")


def cli_args(path):
    return [
        "--run-id", "test-run", "--ranker", "example:calculate", "--out", str(path),
        "--analyzer-model", "fake-analyzer", "--embedding-model", "fake-embedding",
        "--evaluator-model", "fake-evaluator", "--revision", "test-revision",
    ]


def test_cli_writes_complete_run(tmp_path, monkeypatch, components):
    path = tmp_path / "run.json"
    monkeypatch.setattr(runner, "live_components", lambda target: components)
    assert runner.main(cli_args(path)) == 0
    assert load_predictions(path).metadata["revision"] == "test-revision"


def test_cli_retains_incomplete_run_and_returns_one(tmp_path, monkeypatch, components):
    path = tmp_path / "run.json"
    bad = replace(components, analyze=lambda job: None)
    monkeypatch.setattr(runner, "live_components", lambda target: bad)
    assert runner.main(cli_args(path)) == 1
    assert load_predictions(path).cases["dev-01"].analysis is None


def test_cli_rejects_existing_path_before_loading_components(tmp_path, monkeypatch):
    path = tmp_path / "run.json"
    path.write_text("previous run", encoding="utf-8")
    monkeypatch.setattr(runner, "live_components", lambda target: pytest.fail("Must not load components"))
    with pytest.raises(SystemExit) as exc:
        runner.main(cli_args(path))
    assert exc.value.code == 2
    assert path.read_text(encoding="utf-8") == "previous run"