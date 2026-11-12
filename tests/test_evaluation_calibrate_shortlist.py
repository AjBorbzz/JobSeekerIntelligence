import json
from math import inf, nan

import pytest
from pydantic import ValidationError

from app.evaluation import calibrate_shortlist as module
from app.evaluation.dataset import load_dataset
from app.evaluation.score_run import (
    CasePrediction, CoveragePrediction, PredictionRun, dataset_fingerprint, demo_predictions,
)
from app.models.schemas import JobAnalysisData


@pytest.fixture
def dataset():
    return load_dataset()


@pytest.fixture
def run(dataset):
    # Hand-authored test outputs. Never save these as a real observed baseline.
    scores = {"dev-01": 85, "dev-02": 70, "dev-03": 95, "dev-04": 10}
    cases = {}
    for group in dataset.groups:
        if group.split != "dev":
            continue
        for case in group.cases:
            coverage = None if case.poc is None else [
                CoveragePrediction(requirement_type=row.requirement_type, requirement=row.requirement, status="missing")
                for row in case.poc.coverage
            ]
            cases[case.id] = CasePrediction(
                analysis=JobAnalysisData(role_category="fake", role_summary="Test only"),
                relevance_score=scores[case.id], coverage=coverage,
            )
    return PredictionRun(
        schema_version=1, dataset_id=dataset.dataset_id, dataset_sha256=dataset_fingerprint(dataset),
        split="dev", source="observed", run_id="test-only", metadata={"ranking_input": "gold-analysis"}, cases=cases,
    )


def test_selects_cutoff_and_separates_gate_effect(dataset, run):
    original = run.model_dump_json()
    report = module.calibrate(dataset, run)
    assert report["status"] == "development_candidate"
    assert report["candidate_policy"]["min_score"] == 80
    assert report["gate_only"]["shortlisted"] == ["dev-01", "dev-02", "dev-04"]
    assert report["gate_only"]["fp"] == 2
    assert report["selected_comparison"]["score_only"]["shortlisted_violations"] == ["dev-03"]
    assert report["selected_comparison"]["gated"]["shortlisted"] == ["dev-01"]
    assert report["selected_comparison"]["gated"]["fp"] == 0
    assert report["selected_comparison"]["gated"]["recall"] == 1
    assert report["cases"]["dev-03"]["decision"] == "constraint_mismatch"
    assert report["cases"]["dev-03"]["score"] == 95
    assert set(report["cases"]) == set(run.cases)
    assert run.model_dump_json() == original


def test_tie_prefers_lowest_cutoff_with_same_error_counts(dataset, run):
    run.cases["dev-02"].relevance_score = 55
    report = module.calibrate(dataset, run)
    assert report["candidate_policy"]["min_score"] == 60


def test_zero_cutoff_remains_available_when_higher_cutoffs_lose_positive(dataset, run):
    run.cases["dev-01"].relevance_score = 0
    report = module.calibrate(dataset, run)
    assert report["candidate_policy"]["min_score"] == 0
    assert report["selected_comparison"]["gated"]["fn"] == 0


def test_gate_uses_metadata_and_score_boundary(dataset, run):
    group = dataset.groups[0]
    job = group.cases[0].job
    policy = module.ShortlistPolicy.model_validate(module.calibrate(dataset, run)["candidate_policy"])
    assert module.shortlist_decision(job, group.criteria, 80, policy) == "shortlist"
    assert module.shortlist_decision(job, group.criteria, 79.99, policy) == "below_cutoff"
    unknown = job.model_copy(update={"hours_per_week": None})
    assert module.shortlist_decision(unknown, group.criteria, 100, policy) == "review_missing_metadata"
    assert module.shortlist_decision(group.cases[2].job, group.criteria, 100, policy) == "constraint_mismatch"


@pytest.mark.parametrize("score", [True, -1, 101, inf, nan])
def test_rejects_invalid_score(dataset, run, score):
    group = dataset.groups[0]
    policy = module.ShortlistPolicy.model_validate(module.calibrate(dataset, run)["candidate_policy"])
    with pytest.raises(ValueError, match="score must"):
        module.shortlist_decision(group.cases[0].job, group.criteria, score, policy)


def test_policy_rejects_unsupported_rule_version(dataset, run):
    policy = module.calibrate(dataset, run)["candidate_policy"]
    with pytest.raises(ValidationError):
        module.ShortlistPolicy.model_validate({**policy, "rule": "constraints-first-v2"})


def test_demo_and_holdout_are_rejected_before_scoring(dataset, run, monkeypatch):
    monkeypatch.setattr(module, "score_run", lambda *args: pytest.fail("must not score"))
    for wrong in (demo_predictions(dataset), run.model_copy(update={"split": "holdout"})):
        with pytest.raises(ValueError, match="observed dev"):
            module.calibrate(dataset, wrong)


def test_requires_matching_dataset(dataset, run):
    run.dataset_sha256 = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        module.calibrate(dataset, run)


def test_requires_complete_baseline(dataset, run):
    run.cases["dev-01"].coverage = None
    with pytest.raises(ValueError, match="complete baseline"):
        module.calibrate(dataset, run)


def test_requires_fixed_reference_ranking(dataset, run):
    run.metadata["ranking_input"] = "predicted-analysis"
    with pytest.raises(ValueError, match="isolated ranking baseline"):
        module.calibrate(dataset, run)


def test_rejects_no_positive_dev_examples(dataset, run):
    dataset.groups[0].cases[0].relevance_grade = 1
    run.dataset_sha256 = dataset_fingerprint(dataset)
    with pytest.raises(ValueError, match="both grade-2 and non-grade-2"):
        module.calibrate(dataset, run)


def test_cli_writes_candidate_and_refuses_overwrite(tmp_path, run):
    predictions = tmp_path / "test-input.json"
    predictions.write_text(run.model_dump_json(), encoding="utf-8")
    path = tmp_path / "calibration.json"
    args = ["--predictions", str(predictions), "--out", str(path)]
    assert module.main(args) == 0
    before = path.read_bytes()
    assert json.loads(before)["candidate_policy"]["baseline_run_id"] == "test-only"
    with pytest.raises(SystemExit) as exc:
        module.main(args)
    assert exc.value.code == 2
    assert path.read_bytes() == before