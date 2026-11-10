import json
import math

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import DEFAULT_PATH, load_dataset
from app.evaluation.score_run import (
    CasePrediction, CoveragePrediction, dataset_fingerprint, demo_predictions,
    load_predictions, main, score_run,
)


@pytest.fixture
def dataset():
    return load_dataset()


@pytest.fixture
def run(dataset):
    return demo_predictions(dataset)


def test_smoke_report_has_known_extraction_ranking_and_poc_errors(dataset, run):
    report = score_run(dataset, run)
    assert report["source"] == "demo"
    assert report["complete"] is True  # Completeness is not quality.
    extraction = report["extraction"]
    required = extraction["fields"]["required_skills"]
    assert (required["tp"], required["fp"], required["fn"]) == (6, 1, 1)
    assert required["f1"] == pytest.approx(6 / 7)
    assert extraction["seniority_accuracy"] == 1
    assert extraction["forbidden_skill_hits"] == 1
    assert extraction["cases"]["dev-02"]["invalid_quotes"] == 1
    ranking = report["ranking"]["python-backend"]
    assert ranking["pair_counts"] == {"correct": 3, "ties": 0, "wrong": 2}
    assert ranking["pairwise_accuracy"] == pytest.approx(0.6)
    assert ranking["top_case_ids"] == ["dev-03"]
    assert ranking["top_has_constraint_violation"] is True
    assert report["poc"]["accuracy"] == pytest.approx(0.75)
    assert report["poc"]["confusion"]["partial"]["covered"] == 1


def test_rank_ties_get_half_credit_without_case_id_tiebreaking(dataset, run):
    for row in run.cases.values():
        row.relevance_score = 50
    result = score_run(dataset, run)["ranking"]["python-backend"]
    assert result["pair_counts"] == {"correct": 0, "ties": 5, "wrong": 0}
    assert result["pairwise_accuracy"] == 0.5
    assert len(result["top_case_ids"]) == 4
    assert result["top_has_constraint_violation"]


def test_no_comparable_pairs_is_not_a_perfect_score(dataset):
    for case in dataset.groups[0].cases:
        case.relevance_grade = 0
    result = score_run(dataset, demo_predictions(dataset))["ranking"]["python-backend"]
    assert result["complete"]
    assert result["pairwise_accuracy"] is None


def test_null_extraction_keeps_case_in_denominator(dataset, run):
    run.cases["dev-01"].analysis = None
    result = score_run(dataset, run)
    assert not result["complete"]
    assert result["extraction"]["available_cases"] == 3
    assert result["extraction"]["seniority_accuracy"] == 0.75
    assert result["extraction"]["fields"]["required_skills"]["fn"] == 2


def test_null_ranking_score_suppresses_group_metric(dataset, run):
    run.cases["dev-02"].relevance_score = None
    result = score_run(dataset, run)
    assert not result["complete"]
    ranking = result["ranking"]["python-backend"]
    assert ranking["pairwise_accuracy"] is None
    assert ranking["top_case_ids"] is None
    assert ranking["missing_scores"] == ["dev-02"]


def test_zero_score_is_a_valid_result(dataset, run):
    run.cases["dev-02"].relevance_score = 0.0
    assert score_run(dataset, run)["ranking"]["python-backend"]["complete"]


def test_no_evidence_rows_is_not_perfect_quote_grounding(dataset, run):
    for row in run.cases.values():
        row.analysis.evidence = []
    extraction = score_run(dataset, run)["extraction"]
    assert extraction["evidence_rows"] == 0
    assert extraction["exact_quote_rate"] is None


def test_null_poc_not_equivalent_to_missing_label(dataset, run):
    run.cases["dev-01"].coverage = None
    result = score_run(dataset, run)
    assert not result["complete"]
    assert result["poc"]["expected_requirements"] == 4
    assert result["poc"]["predicted_requirements"] == 0
    assert result["poc"]["accuracy"] == 0
    assert result["poc"]["confusion"]["missing"]["no_prediction"] == 1


def test_unexpected_requirement_is_reported_and_run_incomplete(dataset, run):
    run.cases["dev-01"].coverage.append(CoveragePrediction(
        requirement_type="required_skill", requirement="Unrelated skill", status="covered",
    ))
    result = score_run(dataset, run)
    assert not result["complete"]
    assert result["poc"]["accuracy"] == 0.75
    assert result["poc"]["cases"]["dev-01"]["extra_keys"] == [("required_skill", "unrelated skill")]


def test_poc_requirement_key_normalizes_case_and_whitespace(dataset, run):
    row = run.cases["dev-01"].coverage[0]
    row.requirement = "  " + row.requirement.upper() + "  "
    assert score_run(dataset, run)["poc"]["complete"]


def test_reject_coverage_for_job_without_fixed_proposal(dataset, run):
    run.cases["dev-02"].coverage = []
    with pytest.raises(ValueError, match="without a fixed POC"):
        score_run(dataset, run)


def test_duplicate_predicted_requirement_keys_are_invalid():
    with pytest.raises(ValidationError, match="duplicate predicted requirement keys"):
        CasePrediction.model_validate({
            "analysis": None, "relevance_score": 0,
            "coverage": [
                {"requirement_type": "required_skill", "requirement": " Python ", "status": "covered"},
                {"requirement_type": "required_skill", "requirement": "python", "status": "missing"},
            ],
        })


@pytest.mark.parametrize("score", [-1, 101, math.inf, math.nan, True, "90"])
def test_reject_invalid_relevance_score(score):
    with pytest.raises(ValidationError):
        CasePrediction.model_validate({"analysis": None, "relevance_score": score, "coverage": None})


def test_reject_mismatched_dataset_revision(dataset, run):
    dataset.groups[0].cases[0].relevance_rationale = "A corrected annotation."
    with pytest.raises(ValueError, match="dataset ID and fingerprint"):
        score_run(dataset, run)


def test_fingerprint_ignores_json_pretty_printing(dataset, tmp_path):
    original = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "same-dataset.json"
    path.write_text(json.dumps(original, sort_keys=True, indent=4), encoding="utf-8")
    assert dataset_fingerprint(load_dataset(path)) == dataset_fingerprint(dataset)


def test_reject_wrong_split_case_ids(dataset, run):
    run.split = "holdout"
    with pytest.raises(ValueError, match="wrong cases for holdout"):
        score_run(dataset, run)


def test_reject_missing_case_row(dataset, run):
    del run.cases["dev-03"]
    with pytest.raises(ValueError, match="missing=.*dev-03"):
        score_run(dataset, run)


def test_reject_duplicate_json_keys(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"cases":{"dev-01":{},"dev-01":{}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        load_predictions(path)


def test_cli_round_trip(tmp_path, capsys):
    assert main(["--make-demo"]) == 0
    path = tmp_path / "predictions.json"
    path.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["--predictions", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["poc"]["accuracy"] == 0.75


def test_cli_returns_nonzero_but_prints_incomplete_report(run, tmp_path, capsys):
    run.cases["dev-01"].analysis = None
    path = tmp_path / "predictions.json"
    path.write_text(run.model_dump_json(), encoding="utf-8")
    assert main(["--predictions", str(path)]) == 1
    assert not json.loads(capsys.readouterr().out)["complete"]