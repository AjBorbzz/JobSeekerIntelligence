import hashlib
import json
from types import SimpleNamespace

import pytest

from app.evaluation import check_holdout as module
from app.evaluation.calibrate_shortlist import calibrate
from app.evaluation.capture_baseline import Components, capture, save_predictions, synthetic_job
from app.evaluation.dataset import load_dataset, requirement_keys
from app.evaluation.score_run import load_predictions
from app.models.schemas import (
    HybridRelevance, JobAnalysis, POCEvaluationData, POCRequirement, POCRequirementEvaluation,
)


@pytest.fixture
def dataset():
    return load_dataset()


@pytest.fixture
def components(dataset):
    # Hand-authored scores and outputs for the test harness only.
    scores = dict(zip(
        ("dev-01", "dev-02", "dev-03", "dev-04", "holdout-01", "holdout-02", "holdout-03", "holdout-04"),
        (85, 70, 95, 10, 90, 98, 97, 55),
    ))
    by_id = {
        synthetic_job(dataset.dataset_id, case).id: scores[case.id]
        for group in dataset.groups for case in group.cases
    }

    def analyze(job):
        return JobAnalysis(job_id=job.id, role_category="fake", role_summary="Test only")

    def rank(criteria, job, analysis):
        return HybridRelevance(job_id=job.id, query=criteria.query, overall_score=by_id[job.id], components=[])

    def requirements(analysis):
        return [
            POCRequirement(id=f"test-{index}", requirement_type=kind, text=text)
            for index, (kind, text) in enumerate(sorted(requirement_keys(analysis)), 1)
        ]

    def evaluate(requirements, proposal):
        return POCEvaluationData(summary="Test only", requirement_evaluations=[
            POCRequirementEvaluation(requirement_id=row.id, status="missing", explanation="Fake label")
            for row in requirements
        ])

    return Components(analyze, rank, requirements, evaluate, lambda *args: None)


def build_archive(dataset, components):
    metadata = {
        "ranker": "test:rank", "analyzer_model": "fake-a", "embedding_model": "fake-b",
        "evaluator_model": "fake-c", "revision": "test", "config_note": "offline fixtures only",
    }
    baseline = capture(dataset, "dev-test", components, metadata)
    body = json.dumps(calibrate(dataset, baseline)).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    policy = module.frozen_policy(dataset, baseline, body, digest)
    holdout = capture(dataset, "holdout-test", components, {
        **module.recorded_config(baseline), "dev_baseline_run_id": baseline.run_id,
        "frozen_calibration_sha256": digest,
    }, split="holdout")
    return SimpleNamespace(baseline=baseline, body=body, digest=digest, policy=policy, run=holdout)


@pytest.fixture
def archive(dataset, components):
    return build_archive(dataset, components)


def check(dataset, archive):
    return module.check_holdout(dataset, archive.baseline, archive.policy, archive.digest, archive.run)


def test_capture_default_dev_and_explicit_holdout_are_disjoint(dataset, archive):
    assert set(archive.baseline.cases) == {f"dev-0{i}" for i in range(1, 5)}
    assert set(archive.run.cases) == {f"holdout-0{i}" for i in range(1, 5)}
    assert archive.run.split == "holdout"


def test_frozen_policy_keeps_cutoff_and_reports_comparisons(dataset, archive):
    before = archive.policy.model_dump_json()
    report = check(dataset, archive)
    assert report["status"] == "pass"
    assert all(report["checks"].values())
    assert report["policy"]["min_score"] == 80
    assert report["comparisons"]["frozen_policy"]["shortlisted"] == ["holdout-01"]
    assert report["comparisons"]["score_only"]["shortlisted_violations"] == ["holdout-03"]
    assert report["comparisons"]["score_only"]["shortlisted_unknowns"] == ["holdout-02"]
    assert report["cases"]["holdout-02"]["decision"] == "review_missing_metadata"
    assert report["cases"]["holdout-03"]["score"] == 97
    assert archive.policy.model_dump_json() == before


@pytest.mark.parametrize("case_id,score,failed_check", [
    ("holdout-01", 79, "no_grade_2_missed"),
    ("holdout-04", 80, "no_non_grade_2_shortlisted"),
])
def test_failures_do_not_retune_cutoff(dataset, archive, case_id, score, failed_check):
    archive.run.cases[case_id].relevance_score = score
    report = check(dataset, archive)
    assert report["status"] == "fail"
    assert report["checks"][failed_check] is False
    assert report["policy"]["min_score"] == 80


def test_incomplete_holdout_is_reported_but_not_accepted(dataset, archive):
    archive.run.cases["holdout-01"].coverage = None
    report = check(dataset, archive)
    assert report["status"] == "incomplete"
    assert report["comparisons"] is None
    assert report["quality"]["poc"]["expected_requirements"] == 4


def test_one_class_holdout_is_inconclusive(dataset, components):
    group = next(group for group in dataset.groups if group.split == "holdout")
    group.cases[0].relevance_grade = 1
    assert check(dataset, build_archive(dataset, components))["status"] == "inconclusive"


def test_rejects_changed_calibration_bytes(dataset, archive):
    with pytest.raises(ValueError, match="frozen SHA-256"):
        module.frozen_policy(dataset, archive.baseline, archive.body + b"\n", archive.digest)


def test_rejects_baseline_score_changed_after_freeze(dataset, archive):
    archive.baseline.cases["dev-01"].relevance_score = 84
    with pytest.raises(ValueError, match="does not match the development baseline"):
        module.frozen_policy(dataset, archive.baseline, archive.body, archive.digest)


def test_rejects_incomplete_development_baseline(dataset, archive):
    archive.baseline.cases["dev-01"].analysis = None
    with pytest.raises(ValueError, match="development baseline is incomplete"):
        module.frozen_policy(dataset, archive.baseline, archive.body, archive.digest)


@pytest.mark.parametrize("key,value,error", [
    ("embedding_model", "different", "configuration differs"),
    ("frozen_calibration_sha256", "0" * 64, "not linked"),
    ("dev_baseline_run_id", "different-dev", "not linked"),
])
def test_rejects_noncomparable_holdout(dataset, archive, key, value, error):
    archive.run.metadata[key] = value
    with pytest.raises(ValueError, match=error):
        check(dataset, archive)


def test_rejects_demo_as_holdout(dataset, archive):
    archive.run.source = "demo"
    with pytest.raises(ValueError, match="distinct observed holdout"):
        check(dataset, archive)


@pytest.fixture
def cli(tmp_path, archive):
    baseline, calibration, predictions = [tmp_path / name for name in ("dev.json", "calibration.json", "holdout.json")]
    save_predictions(baseline, archive.baseline)
    save_predictions(predictions, archive.run)
    calibration.write_bytes(archive.body)
    out = tmp_path / "report.json"
    args = [
        "--baseline", str(baseline), "--calibration", str(calibration),
        "--frozen-sha256", archive.digest, "--out", str(out),
    ]
    return SimpleNamespace(args=args, out=out, predictions=predictions)


def test_cli_replays_without_loading_live_components(cli, monkeypatch):
    monkeypatch.setattr(module, "live_components", lambda *args: pytest.fail("replay must stay offline"))
    assert module.main([*cli.args, "--predictions", str(cli.predictions)]) == 0
    assert json.loads(cli.out.read_text())["status"] == "pass"


def test_cli_requires_confirmation_before_loading_live_components(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "live_components", lambda *args: pytest.fail("must not capture without confirmation"))
    args = [*cli.args, "--capture", "--run-id", "holdout-test", "--predictions-out", str(tmp_path / "new.json")]
    with pytest.raises(SystemExit) as exc:
        module.main(args)
    assert exc.value.code == 2
    assert not cli.out.exists()


def test_cli_capture_persists_holdout_predictions_and_report(cli, tmp_path, components, monkeypatch):
    monkeypatch.setattr(module, "live_components", lambda target: components)
    path = tmp_path / "new.json"
    assert module.main([
        *cli.args, "--capture", "--confirm-config", "--run-id", "holdout-test", "--predictions-out", str(path),
    ]) == 0
    assert load_predictions(path).split == "holdout"
    assert json.loads(cli.out.read_text())["status"] == "pass"


def test_cli_preserves_existing_report(cli):
    cli.out.write_text("existing", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        module.main([*cli.args, "--predictions", str(cli.predictions)])
    assert exc.value.code == 2
    assert cli.out.read_text(encoding="utf-8") == "existing"