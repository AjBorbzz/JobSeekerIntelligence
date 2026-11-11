import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter

from app.evaluation.dataset import (
    DEFAULT_PATH, EvaluationCase, EvaluationDataset, Slug, load_dataset, normalized, requirement_keys,
)
from app.evaluation.score_run import (
    CasePrediction, CoveragePrediction, PredictionRun, dataset_fingerprint, score_run,
)
from app.models.schemas import (
    HybridRelevance, Job, JobAnalysis, JobAnalysisData, POCEvaluationData,
    POCProposal, POCRequirement, SearchCriteria,
)


@dataclass(frozen=True)
class Components:
    analyze: Callable[[Job], JobAnalysis]
    rank: Callable[[SearchCriteria, Job, JobAnalysis], HybridRelevance]
    build_requirements: Callable[[JobAnalysis], list[POCRequirement]]
    evaluate: Callable[[list[POCRequirement], POCProposal], POCEvaluationData]
    validate_assessment: Callable[[list[POCRequirement], POCProposal, POCEvaluationData], None]


def resolve_ranker(target: str) -> Callable:
    module, separator, attribute = target.partition(":")
    if not separator or not all(part.isidentifier() for part in module.split(".") + attribute.split(".")):
        raise ValueError("ranker must be a local module:attribute.path")
    result = import_module(module)
    for name in attribute.split("."):
        result = getattr(result, name)
    if not callable(result):
        raise ValueError("ranker target is not callable")
    return result


def live_components(ranker_target: str) -> Components:
    # Keep app service imports out of offline tests and --help.
    rank = resolve_ranker(ranker_target)
    from app.services.analysis_service import analysis_service
    from app.services.poc_evaluation_service import (
        build_requirements, poc_evaluation_service, validate_assessment,
    )

    return Components(
        analyze=analysis_service.analyzer.analyze, rank=rank,
        build_requirements=build_requirements, evaluate=poc_evaluation_service.evaluator.evaluate,
        validate_assessment=validate_assessment,
    )


def synthetic_job(dataset_id: str, case: EvaluationCase) -> Job:
    return Job(
        **case.job.model_dump(),
        id=uuid5(NAMESPACE_URL, f"job-intelligence-evaluation/{dataset_id}/{case.id}"),
        created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )


def extraction(components: Components, job: Job) -> JobAnalysisData:
    result = JobAnalysis.model_validate(components.analyze(job.model_copy(deep=True)))
    if result.job_id != job.id:
        raise ValueError("analysis belongs to a different job")
    return JobAnalysisData.model_validate(result.model_dump(exclude={"job_id"}))


def relevance(components: Components, job: Job, reference: JobAnalysis, criteria: SearchCriteria) -> float:
    result = HybridRelevance.model_validate(
        components.rank(criteria.model_copy(deep=True), job.model_copy(deep=True), reference.model_copy(deep=True))
    )
    if result.job_id != job.id or result.query != criteria.query:
        raise ValueError("relevance result does not match the job and query")
    return result.overall_score


def poc_coverage(
    components: Components, case: EvaluationCase, reference: JobAnalysis, criteria: SearchCriteria,
) -> list[CoveragePrediction]:
    if case.poc is None:
        raise ValueError("case has no fixed POC")
    requirements = components.build_requirements(reference.model_copy(deep=True))
    by_id = {row.id: row for row in requirements}
    keys = {(row.requirement_type, normalized(row.text)) for row in requirements}
    if (not requirements or len(by_id) != len(requirements) or len(keys) != len(requirements)
            or keys != requirement_keys(reference)):
        raise ValueError("requirement builder differs from the fixture contract")

    proposal = POCProposal(
        **case.poc.proposal.model_dump(),
        job_id=reference.job_id, search_query=criteria.query,
        job_relevance_score=0.0, generated_by="synthetic-fixture",
    )
    assessment = POCEvaluationData.model_validate(
        components.evaluate([row.model_copy(deep=True) for row in requirements], proposal.model_copy(deep=True))
    )
    components.validate_assessment(requirements, proposal, assessment)
    returned = [row.requirement_id for row in assessment.requirement_evaluations]
    if len(returned) != len(set(returned)) or set(returned) != set(by_id):
        raise ValueError("evaluator returned missing, extra, or duplicate IDs")
    return [
        CoveragePrediction(
            requirement_type=by_id[row.requirement_id].requirement_type,
            requirement=by_id[row.requirement_id].text, status=row.status,
        )
        for row in assessment.requirement_evaluations
    ]


def capture(
    dataset: EvaluationDataset, run_id: str, components: Components, metadata: dict[str, str] | None = None,
) -> PredictionRun:
    run_id = TypeAdapter(Slug).validate_python(run_id)
    notes = dict(metadata or {})
    notes.update(
        started_at_utc=datetime.now(timezone.utc).isoformat(),
        python_version=sys.version.split()[0],
        ranking_input="gold-analysis",
        poc_input="gold-analysis-and-fixed-proposal",
    )
    rows = {}

    def attempt(case_id, stage, operation):
        try:
            return operation()
        except Exception as exc:
            # Some model errors embed raw output. Store the class only.
            notes[f"failure.{case_id}.{stage}"] = type(exc).__name__
            print(f"{case_id} {stage}: {type(exc).__name__}", file=sys.stderr)
            return None

    for group in dataset.groups:
        if group.split != "dev":
            continue
        for case in group.cases:
            job = synthetic_job(dataset.dataset_id, case)
            reference = JobAnalysis(**case.analysis_gold.model_dump(), job_id=job.id)
            rows[case.id] = CasePrediction(
                analysis=attempt(case.id, "extraction", lambda: extraction(components, job)),
                relevance_score=attempt(case.id, "relevance", lambda: relevance(
                    components, job, reference, group.criteria,
                )),
                coverage=attempt(case.id, "poc", lambda: poc_coverage(
                    components, case, reference, group.criteria,
                )) if case.poc is not None else None,
            )

    notes["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return PredictionRun(
        schema_version=1, dataset_id=dataset.dataset_id, dataset_sha256=dataset_fingerprint(dataset),
        split="dev", run_id=run_id, source="observed", metadata=notes, cases=rows,
    )


def save_predictions(path: Path, run: PredictionRun) -> None:
    serialized = run.model_dump_json(indent=2) + "\n"
    # Exclusive create prevents replacing an earlier run.
    with path.open("x", encoding="utf-8") as file:
        file.write(serialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a development baseline using the existing app components.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ranker", required=True, help="local module:attribute.path of the pure score callable")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--analyzer-model", required=True, help="effective configured tag; recorded, not set")
    parser.add_argument("--embedding-model", required=True, help="effective configured tag; recorded, not set")
    parser.add_argument("--evaluator-model", required=True, help="effective configured tag; recorded, not set")
    parser.add_argument("--revision", required=True, help="code revision; recorded, not set")
    parser.add_argument("--config-note", default="", help="effective config/dirty-tree note; no secrets")
    args = parser.parse_args(argv)
    try:
        if args.out.exists():
            raise ValueError("output already exists; use a new filename")
        if not args.out.parent.is_dir():
            raise ValueError("create the output directory first")
        run_id = TypeAdapter(Slug).validate_python(args.run_id)
        dataset = load_dataset(args.dataset)
        components = live_components(args.ranker)
        run = capture(dataset, run_id, components, metadata={
            "ranker": args.ranker, "analyzer_model": args.analyzer_model,
            "embedding_model": args.embedding_model, "evaluator_model": args.evaluator_model,
            "revision": args.revision, "config_note": args.config_note,
        })
        report = score_run(dataset, run)
        save_predictions(args.out, run)
    except (OSError, ValueError, ImportError, AttributeError, TypeError) as exc:
        parser.error(str(exc))

    print(f"{run.run_id}: split=dev cases={len(run.cases)} complete={report['complete']}")
    print(f"Predictions: {args.out}")
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())