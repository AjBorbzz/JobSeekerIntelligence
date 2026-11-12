import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.evaluation.dataset import (
    DEFAULT_PATH, DatasetModel, EvaluationDataset, Slug, constraint_fit, load_dataset,
)
from app.evaluation.score_run import Digest, PredictionRun, load_predictions, ratio, score_run
from app.models.schemas import JobCreate, SearchCriteria

CUTOFFS = (0, 50, 60, 70, 80, 90, 100)
Decision = Literal["shortlist", "below_cutoff", "review_missing_metadata", "constraint_mismatch"]


class ShortlistPolicy(DatasetModel):
    schema_version: int = Field(ge=1, le=1, strict=True)
    rule: Literal["constraints-first-v1"]
    dataset_id: Slug
    dataset_sha256: Digest
    baseline_run_id: Slug
    min_score: int = Field(ge=0, le=100, strict=True)


def shortlist_decision(job: JobCreate, criteria: SearchCriteria, score: float, policy: ShortlistPolicy) -> Decision:
    if isinstance(score, bool) or not 0 <= score <= 100:
        raise ValueError("score must be a number from 0 to 100")
    fit = constraint_fit(job, criteria)
    if fit == "violates":
        return "constraint_mismatch"
    if fit == "unknown":
        return "review_missing_metadata"
    return "shortlist" if score >= policy.min_score else "below_cutoff"


def summarize(selected: set[str], positive: set[str], universe: set[str], fits: dict[str, str]) -> dict:
    tp, fp, fn = len(selected & positive), len(selected - positive), len(positive - selected)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": len(universe - (selected | positive)),
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
        "shortlisted": sorted(selected),
        "false_positives": sorted(selected - positive), "false_negatives": sorted(positive - selected),
        "shortlisted_violations": sorted(case_id for case_id in selected if fits[case_id] == "violates"),
        "shortlisted_unknowns": sorted(case_id for case_id in selected if fits[case_id] == "unknown"),
    }


def calibrate(dataset: EvaluationDataset, run: PredictionRun) -> dict:
    if run.split != "dev" or run.source != "observed":
        raise ValueError("calibration requires an observed dev run, not demo or holdout")
    if run.metadata.get("ranking_input") != "gold-analysis":
        raise ValueError("use the isolated ranking baseline from 12B Part 2")
    baseline = score_run(dataset, run)
    if not baseline["complete"]:
        raise ValueError("calibration requires a complete baseline")

    rows = [(case, group.criteria) for group in dataset.groups if group.split == "dev" for case in group.cases]
    universe = {case.id for case, _ in rows}
    positive = {case.id for case, _ in rows if case.relevance_grade == 2}
    if not positive or positive == universe:
        raise ValueError("development cases must include both grade-2 and non-grade-2 examples")
    fits = {case.id: constraint_fit(case.job, criteria) for case, criteria in rows}
    scores = {}
    for case, _ in rows:
        score = run.cases[case.id].relevance_score
        if score is None:
            raise ValueError(f"missing relevance score: {case.id}")
        scores[case.id] = score

    sweep = []
    for cutoff in CUTOFFS:
        policy = ShortlistPolicy(
            schema_version=1, rule="constraints-first-v1", dataset_id=dataset.dataset_id,
            dataset_sha256=run.dataset_sha256, baseline_run_id=run.run_id, min_score=cutoff,
        )
        decisions = {
            case.id: shortlist_decision(case.job, criteria, scores[case.id], policy)
            for case, criteria in rows
        }
        gated = {case_id for case_id, decision in decisions.items() if decision == "shortlist"}
        score_only = {case_id for case_id, score in scores.items() if score >= cutoff}
        sweep.append({
            "policy": policy.model_dump(mode="json"),
            "score_only": summarize(score_only, positive, universe, fits),
            "gated": summarize(gated, positive, universe, fits),
            "decisions": decisions,
        })

    feasible = [row for row in sweep if row["gated"]["fn"] == 0]
    if not feasible:
        raise ValueError("no cutoff retains all grade-2 development cases; inspect the fixture and run")
    selected = min(feasible, key=lambda row: (row["gated"]["fp"], row["policy"]["min_score"]))
    return {
        "schema_version": 1, "status": "development_candidate", "split": "dev",
        "target": "grade-2 shortlist", "positive_count": len(positive), "case_count": len(universe),
        "baseline_metadata": run.metadata,
        "baseline_ranking": baseline["ranking"],
        "candidate_policy": selected["policy"],
        "selected_comparison": {"score_only": selected["score_only"], "gated": selected["gated"]},
        "gate_only": sweep[0]["gated"],
        "cases": {
            case.id: {
                "score": scores[case.id], "expected_grade": case.relevance_grade,
                "constraint_fit": fits[case.id], "decision": selected["decisions"][case.id],
            }
            for case, _ in rows
        },
        "sweep": sweep,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select a dev-only shortlist policy without changing model scores.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.out.exists():
            raise ValueError("output already exists; use a new filename")
        report = calibrate(load_dataset(args.dataset), load_predictions(args.predictions))
        body = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        with args.out.open("x", encoding="utf-8") as file:
            file.write(body)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Candidate cutoff: {report['candidate_policy']['min_score']} (development only)")
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())