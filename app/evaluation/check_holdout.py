import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.evaluation.calibrate_shortlist import CUTOFFS, ShortlistPolicy, shortlist_decision, summarize
from app.evaluation.capture_baseline import capture, live_components, save_predictions
from app.evaluation.dataset import (
    DEFAULT_PATH, EvaluationDataset, _reject_constant, _unique_keys, constraint_fit, load_dataset,
)
from app.evaluation.score_run import PredictionRun, load_predictions, score_run

CONFIG_KEYS = (
    "ranker", "analyzer_model", "embedding_model", "evaluator_model", "revision",
    "config_note", "python_version", "ranking_input", "poc_input",
)


def recorded_config(run: PredictionRun) -> dict[str, str]:
    for key in CONFIG_KEYS:
        if key not in run.metadata or (key != "config_note" and not run.metadata[key].strip()):
            raise ValueError(f"missing run configuration: {key}")
    config = {key: run.metadata[key] for key in CONFIG_KEYS}
    if (config["ranking_input"] != "gold-analysis"
            or config["poc_input"] != "gold-analysis-and-fixed-proposal"):
        raise ValueError("expected the isolated 12B capture settings")
    return config


def frozen_policy(
    dataset: EvaluationDataset, baseline: PredictionRun, body: bytes, expected_sha256: str,
) -> ShortlistPolicy:
    if hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError("calibration file does not match the frozen SHA-256")
    if baseline.source != "observed" or baseline.split != "dev":
        raise ValueError("freeze requires the observed development baseline")
    recorded_config(baseline)
    before = score_run(dataset, baseline)
    if not before["complete"]:
        raise ValueError("development baseline is incomplete")

    report = json.loads(body, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    if (not isinstance(report, dict) or report.get("schema_version") != 1
            or report.get("status") != "development_candidate" or report.get("split") != "dev"):
        raise ValueError("expected a 12C development calibration report")
    policy = ShortlistPolicy.model_validate(report.get("candidate_policy"))
    if (policy.dataset_id != baseline.dataset_id or policy.dataset_sha256 != baseline.dataset_sha256
            or policy.baseline_run_id != baseline.run_id or policy.min_score not in CUTOFFS
            or report.get("baseline_metadata") != baseline.metadata
            or report.get("baseline_ranking") != before["ranking"]):
        raise ValueError("frozen policy does not match the development baseline")
    return policy


def check_holdout(
    dataset: EvaluationDataset, baseline: PredictionRun, policy: ShortlistPolicy,
    calibration_sha256: str, run: PredictionRun,
) -> dict:
    if run.source != "observed" or run.split != "holdout" or run.run_id == baseline.run_id:
        raise ValueError("use a distinct observed holdout run")
    if recorded_config(run) != recorded_config(baseline):
        raise ValueError("holdout configuration differs from the recorded baseline")
    if (run.metadata.get("frozen_calibration_sha256") != calibration_sha256
            or run.metadata.get("dev_baseline_run_id") != policy.baseline_run_id
            or run.dataset_sha256 != policy.dataset_sha256 or run.dataset_id != policy.dataset_id):
        raise ValueError("holdout run is not linked to the frozen calibration")

    quality = score_run(dataset, run)
    result = {
        "schema_version": 1, "status": "incomplete", "frozen_calibration_sha256": calibration_sha256,
        "policy": policy.model_dump(mode="json"), "quality": quality,
        "comparisons": None, "checks": None, "cases": {},
    }
    if not quality["complete"]:
        return result

    rows = [(case, group.criteria) for group in dataset.groups if group.split == "holdout" for case in group.cases]
    universe = {case.id for case, _ in rows}
    positive = {case.id for case, _ in rows if case.relevance_grade == 2}
    fits, decisions, scores = {}, {}, {}
    for case, criteria in rows:
        score = run.cases[case.id].relevance_score
        if score is None:
            raise ValueError(f"missing score in complete run: {case.id}")
        scores[case.id] = score
        fits[case.id] = constraint_fit(case.job, criteria)
        decisions[case.id] = shortlist_decision(case.job, criteria, score, policy)

    chosen = {case_id for case_id, decision in decisions.items() if decision == "shortlist"}
    score_only = {case_id for case_id, score in scores.items() if score >= policy.min_score}
    gate_only = {case_id for case_id, fit in fits.items() if fit == "meets"}
    gated = summarize(chosen, positive, universe, fits)
    checks = {
        "both_label_classes_present": bool(positive and universe - positive),
        "no_known_violations_shortlisted": not gated["shortlisted_violations"],
        "no_unknown_constraints_shortlisted": not gated["shortlisted_unknowns"],
        "no_grade_2_missed": gated["fn"] == 0,
        "no_non_grade_2_shortlisted": gated["fp"] == 0,
    }
    status = "inconclusive" if not checks["both_label_classes_present"] else (
        "pass" if all(checks.values()) else "fail"
    )
    result.update(
        status=status, checks=checks,
        comparisons={
            "score_only": summarize(score_only, positive, universe, fits),
            "gate_only": summarize(gate_only, positive, universe, fits),
            "frozen_policy": gated,
        },
        cases={
            case.id: {"score": scores[case.id], "expected_grade": case.relevance_grade,
                      "constraint_fit": fits[case.id], "decision": decisions[case.id]}
            for case, _ in rows
        },
    )
    return result


def require_new_output(path: Path) -> None:
    if path.exists() or not path.parent.is_dir():
        raise ValueError(f"use a new output path in an existing directory: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the frozen shortlist rule on the held-out split.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--frozen-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", action="store_true")
    mode.add_argument("--predictions", type=Path, help="replay an existing held-out run without inference")
    parser.add_argument("--run-id")
    parser.add_argument("--predictions-out", type=Path)
    parser.add_argument("--confirm-config", action="store_true", help="you verified the effective local configuration")
    args = parser.parse_args(argv)
    try:
        require_new_output(args.out)
        dataset = load_dataset(args.dataset)
        baseline = load_predictions(args.baseline)
        policy = frozen_policy(dataset, baseline, args.calibration.read_bytes(), args.frozen_sha256)
        if args.capture:
            if not args.confirm_config or not args.run_id or not args.predictions_out:
                raise ValueError("capture requires --confirm-config, --run-id, and --predictions-out")
            if args.run_id == baseline.run_id or args.out.resolve() == args.predictions_out.resolve():
                raise ValueError("use a distinct run ID and separate output paths")
            require_new_output(args.predictions_out)
            config = recorded_config(baseline)
            if config["python_version"] != sys.version.split()[0]:
                raise ValueError("use the same Python version as the baseline")
            metadata = {
                **config, "frozen_calibration_sha256": args.frozen_sha256,
                "dev_baseline_run_id": baseline.run_id,
            }
            run = capture(dataset, args.run_id, live_components(config["ranker"]), metadata, split="holdout")
        else:
            if args.confirm_config or args.run_id or args.predictions_out:
                raise ValueError("capture-only options are not valid for replay")
            run = load_predictions(args.predictions)

        report = check_holdout(dataset, baseline, policy, args.frozen_sha256, run)
        if args.capture:
            save_predictions(args.predictions_out, run)
        with args.out.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            file.write("\n")
    except (OSError, ValueError, ImportError, AttributeError, TypeError) as exc:
        parser.error(str(exc))

    print(f"{run.run_id}: {report['status']}")
    print(f"Report: {args.out}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())