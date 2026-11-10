import argparse
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.evaluation.dataset import (
    DEFAULT_PATH, DatasetModel, EvaluationCase, EvaluationDataset, Note, QueryGroup,
    Slug, Split, _reject_constant, _unique_keys, load_dataset, normalized,
)
from app.models.schemas import (
    AnalysisEvidence, EvidenceCategory, JobAnalysisData, POCCoverageStatus, POCRequirementType,
)

Score = Annotated[float, Field(ge=0, le=100, strict=True, allow_inf_nan=False)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
FIELDS = ("required_skills", "preferred_skills", "responsibilities")
COVERAGE_STATES = ("covered", "partial", "missing", "no_prediction")


class CoveragePrediction(DatasetModel):
    requirement_type: POCRequirementType
    requirement: Note
    status: POCCoverageStatus

    def key(self) -> tuple[str, str]:
        return self.requirement_type.value, normalized(self.requirement)


class CasePrediction(DatasetModel):
    # Null represents an unavailable result, not a passing result.
    analysis: JobAnalysisData | None
    relevance_score: Score | None
    coverage: list[CoveragePrediction] | None

    @model_validator(mode="after")
    def check_coverage_keys(self):
        keys = [row.key() for row in self.coverage or []]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate predicted requirement keys")
        return self


class PredictionRun(DatasetModel):
    schema_version: int = Field(ge=1, le=1, strict=True)
    dataset_id: Slug
    dataset_sha256: Digest
    split: Split
    run_id: Slug
    source: Literal["demo", "observed"]
    metadata: dict[str, str] = Field(default_factory=dict)
    cases: dict[Slug, CasePrediction] = Field(min_length=1)


def dataset_fingerprint(dataset: EvaluationDataset) -> str:
    canonical = json.dumps(
        dataset.model_dump(mode="json"),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_predictions(path: Path) -> PredictionRun:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys,
                      parse_constant=_reject_constant)
    return PredictionRun.model_validate(data)


def ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def label_set(values: list[str]) -> set[str]:
    return {normalized(value) for value in values}


def score_extraction(cases: list[EvaluationCase], run: PredictionRun) -> dict:
    counts = {field: Counter() for field in FIELDS}
    details = {}
    available = correct_seniority = valid_quotes = all_quotes = forbidden_hits = 0
    for case in cases:
        result = run.cases[case.id].analysis
        available += result is not None
        gold = case.analysis_gold
        predicted_seniority = result.seniority.value if result is not None else None
        correct_seniority += predicted_seniority == gold.seniority.value
        differences = {}
        for field in FIELDS:
            expected = label_set(getattr(gold, field))
            actual = label_set(getattr(result, field)) if result is not None else set()
            counts[field].update(tp=len(expected & actual), fp=len(actual - expected),
                                 fn=len(expected - actual))
            differences[field] = {"missing": sorted(expected - actual), "extra": sorted(actual - expected)}

        evidence = result.evidence if result is not None else []
        valid = sum(bool(item.source_text.strip()) and item.source_text in case.job.job_overview
                    for item in evidence)
        actual_skills = label_set(result.required_skills + result.preferred_skills) if result is not None else set()
        forbidden = sorted(actual_skills & label_set(case.forbidden_skills))
        valid_quotes += valid
        all_quotes += len(evidence)
        forbidden_hits += len(forbidden)
        details[case.id] = {
            "available": result is not None,
            "differences": differences,
            "expected_seniority": gold.seniority.value,
            "predicted_seniority": predicted_seniority,
            "invalid_quotes": len(evidence) - valid,
            "forbidden_skills": forbidden,
        }

    fields = {}
    for field, count in counts.items():
        tp, fp, fn = count["tp"], count["fp"], count["fn"]
        fields[field] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn),
        }
    return {
        "expected_cases": len(cases), "available_cases": available, "fields": fields,
        "seniority_correct": correct_seniority,
        "seniority_accuracy": ratio(correct_seniority, len(cases)),
        "exact_quotes": valid_quotes, "evidence_rows": all_quotes,
        "exact_quote_rate": ratio(valid_quotes, all_quotes),
        "forbidden_skill_hits": forbidden_hits, "cases": details,
    }


def score_ranking(group: QueryGroup, run: PredictionRun) -> dict:
    rows = [
        {"case_id": case.id, "grade": case.relevance_grade,
         "constraint_fit": case.constraint_fit, "score": run.cases[case.id].relevance_score}
        for case in group.cases
    ]
    missing = [row["case_id"] for row in rows if row["score"] is None]
    if missing:
        return {
            "complete": False, "missing_scores": missing, "pair_counts": None,
            "pairwise_accuracy": None, "top_case_ids": None,
            "top_has_constraint_violation": None, "candidates": rows,
        }

    correct = ties = wrong = 0
    for left, right in combinations(rows, 2):
        grade_delta = left["grade"] - right["grade"]
        if grade_delta == 0:
            continue
        score_delta = left["score"] - right["score"]
        if score_delta == 0:
            ties += 1
        elif score_delta * grade_delta > 0:
            correct += 1
        else:
            wrong += 1
    ranked = sorted(rows, key=lambda row: (-row["score"], row["case_id"]))
    top = [row for row in ranked if row["score"] == ranked[0]["score"]]
    return {
        "complete": True, "missing_scores": [],
        "pair_counts": {"correct": correct, "ties": ties, "wrong": wrong},
        "pairwise_accuracy": ratio(correct + 0.5 * ties, correct + ties + wrong),
        "top_case_ids": [row["case_id"] for row in top],
        "top_has_constraint_violation": any(row["constraint_fit"] == "violates" for row in top),
        "candidates": ranked,
    }


def score_poc(cases: list[EvaluationCase], run: PredictionRun) -> dict:
    confusion = {state: dict.fromkeys(COVERAGE_STATES, 0) for state in COVERAGE_STATES[:-1]}
    details = {}
    expected_count = predicted_count = correct = 0
    complete = True
    for case in cases:
        predictions = run.cases[case.id].coverage
        if case.poc is None:
            if predictions is not None:
                raise ValueError(f"{case.id}: coverage supplied without a fixed POC")
            continue
        expected = {
            (row.requirement_type.value, normalized(row.requirement)): row.status.value
            for row in case.poc.coverage
        }
        actual = {row.key(): row.status.value for row in predictions or []}
        extra = sorted(actual.keys() - expected.keys())
        missing = sorted(expected.keys() - actual.keys())
        complete = complete and not extra and not missing
        expected_count += len(expected)
        predicted_count += len(expected.keys() & actual.keys())
        rows = []
        for key, gold in sorted(expected.items()):
            label = actual.get(key, "no_prediction")
            confusion[gold][label] += 1
            correct += gold == label
            rows.append({"requirement_type": key[0], "requirement": key[1],
                         "expected": gold, "predicted": label})
        details[case.id] = {"missing_keys": missing, "extra_keys": extra, "requirements": rows}
    return {
        "complete": complete, "expected_requirements": expected_count,
        "predicted_requirements": predicted_count, "correct": correct,
        "accuracy": ratio(correct, expected_count), "confusion": confusion, "cases": details,
    }


def score_run(dataset: EvaluationDataset, run: PredictionRun) -> dict:
    if run.dataset_id != dataset.dataset_id or run.dataset_sha256 != dataset_fingerprint(dataset):
        raise ValueError("prediction run does not match the dataset ID and fingerprint")
    groups = [group for group in dataset.groups if group.split == run.split]
    cases = [case for group in groups for case in group.cases]
    expected = {case.id for case in cases}
    actual = set(run.cases)
    if expected != actual:
        raise ValueError(f"wrong cases for {run.split}: missing={sorted(expected - actual)}, "
                         f"unexpected={sorted(actual - expected)}")

    extraction = score_extraction(cases, run)
    rankings = {group.id: score_ranking(group, run) for group in groups}
    poc = score_poc(cases, run)
    complete = (extraction["available_cases"] == len(cases)
                and all(item["complete"] for item in rankings.values()) and poc["complete"])
    return {
        "schema_version": 1, "dataset_id": run.dataset_id, "dataset_sha256": run.dataset_sha256,
        "split": run.split, "run_id": run.run_id, "source": run.source, "metadata": run.metadata,
        "complete": complete, "extraction": extraction, "ranking": rankings, "poc": poc,
    }


def demo_predictions(dataset: EvaluationDataset) -> PredictionRun:
    # Deliberately uses gold data to test the scorer. This is not inference.
    scores = {"dev-01": 85, "dev-02": 70, "dev-03": 95, "dev-04": 10}
    cases = [case for group in dataset.groups if group.split == "dev" for case in group.cases]
    if dataset.dataset_id != "synthetic-v1" or {case.id for case in cases} != set(scores):
        raise ValueError("demo requires the original synthetic-v1 development fixture")
    results = {}
    for case in cases:
        analysis = case.analysis_gold.model_copy(deep=True)
        if case.id == "dev-01":
            analysis.required_skills = [skill for skill in analysis.required_skills if normalized(skill) != "fastapi"]
            analysis.evidence = [
                item for item in analysis.evidence
                if not (item.category == EvidenceCategory.REQUIRED_SKILL and normalized(item.claim) == "fastapi")
            ]
        elif case.id == "dev-02":
            analysis.required_skills.append("FastAPI")
            analysis.evidence.append(AnalysisEvidence(
                category=EvidenceCategory.REQUIRED_SKILL, claim="FastAPI",
                source_text="FastAPI expertise is a firm requirement.",
            ))
        coverage = None
        if case.poc is not None:
            coverage = [
                CoveragePrediction(
                    requirement_type=row.requirement_type, requirement=row.requirement,
                    status=(POCCoverageStatus.COVERED if row.status == POCCoverageStatus.PARTIAL else row.status),
                )
                for row in case.poc.coverage
            ]
        results[case.id] = CasePrediction(
            analysis=analysis, relevance_score=scores[case.id], coverage=coverage,
        )
    return PredictionRun(
        schema_version=1, dataset_id=dataset.dataset_id, dataset_sha256=dataset_fingerprint(dataset),
        split="dev", run_id="synthetic-scorer-smoke", source="demo", cases=results,
        metadata={"purpose": "gold-derived smoke test; not a model baseline"},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score saved Job Intelligence benchmark predictions.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATH)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--make-demo", action="store_true")
    mode.add_argument("--predictions", type=Path)
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.make_demo:
            result = demo_predictions(dataset).model_dump(mode="json")
            exit_code = 0
        else:
            result = score_run(dataset, load_predictions(args.predictions))
            exit_code = 0 if result["complete"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return exit_code
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())