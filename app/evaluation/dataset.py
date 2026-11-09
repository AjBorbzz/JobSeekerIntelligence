import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.schemas import (
    EvidenceCategory, JobAnalysisData, JobCreate, POCCoverageStatus,
    POCProposalData, POCRequirementType, SearchCriteria, SeniorityLevel, WorkType,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$")]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Split = Literal["dev", "holdout"]
ConstraintFit = Literal["meets", "violates", "unknown"]
DEFAULT_PATH = Path("tests/fixtures/evaluation/synthetic-v1.json")


def normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CoverageLabel(DatasetModel):
    requirement_type: POCRequirementType
    requirement: Note
    status: POCCoverageStatus
    project_evidence: list[str]
    rationale: Note


class FixedPOC(DatasetModel):
    proposal: POCProposalData
    coverage: list[CoverageLabel] = Field(min_length=1)


def requirement_keys(analysis: JobAnalysisData) -> set[tuple[POCRequirementType, str]]:
    groups = {
        POCRequirementType.REQUIRED_SKILL: analysis.required_skills,
        POCRequirementType.RESPONSIBILITY: analysis.responsibilities,
        POCRequirementType.PAIN_POINT: analysis.employer_pain_points,
        POCRequirementType.DELIVERABLE: analysis.expected_deliverables,
        POCRequirementType.BUSINESS_PROBLEM: [analysis.business_problem] if analysis.business_problem else [],
    }
    return {(kind, normalized(text)) for kind, values in groups.items() for text in values if normalized(text)}


class EvaluationCase(DatasetModel):
    id: Slug
    job: JobCreate
    analysis_gold: JobAnalysisData
    forbidden_skills: list[Note] = Field(default_factory=list)
    constraint_fit: ConstraintFit
    relevance_grade: int = Field(ge=0, le=2, strict=True)
    relevance_rationale: Note
    poc: FixedPOC | None = None

    @model_validator(mode="after")
    def check_labels(self):
        analysis = self.analysis_gold
        groups = {
            EvidenceCategory.REQUIRED_SKILL: analysis.required_skills,
            EvidenceCategory.PREFERRED_SKILL: analysis.preferred_skills,
            EvidenceCategory.RESPONSIBILITY: analysis.responsibilities,
        }
        available = set()
        for item in analysis.evidence:
            if not item.source_text.strip() or item.source_text not in self.job.job_overview:
                raise ValueError(f"{self.id}: evidence must be an exact job overview quote")
            available.add((item.category, normalized(item.claim)))
        for category, values in groups.items():
            keys = [normalized(value) for value in values]
            if "" in keys or len(set(keys)) != len(keys):
                raise ValueError(f"{self.id}: blank or duplicate labels in {category.value}")
            if any((category, key) not in available for key in keys):
                raise ValueError(f"{self.id}: missing evidence for {category.value}")
        if analysis.seniority != SeniorityLevel.UNKNOWN:
            if (EvidenceCategory.SENIORITY, analysis.seniority.value) not in available:
                raise ValueError(f"{self.id}: known seniority requires evidence")
        required = set(map(normalized, analysis.required_skills))
        preferred = set(map(normalized, analysis.preferred_skills))
        forbidden = set(map(normalized, self.forbidden_skills))
        if required & preferred or (required | preferred) & forbidden:
            raise ValueError(f"{self.id}: overlapping required, preferred, or forbidden skills")

        if self.poc is not None:
            keys = [(row.requirement_type, normalized(row.requirement)) for row in self.poc.coverage]
            if len(keys) != len(set(keys)) or set(keys) != requirement_keys(analysis):
                raise ValueError(f"{self.id}: POC labels must cover every gold requirement exactly once")
            sources = [feature.description for feature in self.poc.proposal.features]
            for row in self.poc.coverage:
                if row.status == POCCoverageStatus.MISSING:
                    if row.project_evidence:
                        raise ValueError(f"{self.id}: missing coverage cannot carry evidence")
                elif not row.project_evidence or any(
                    not quote.strip() or not any(quote in source for source in sources)
                    for quote in row.project_evidence
                ):
                    raise ValueError(f"{self.id}: POC evidence must quote a feature description exactly")
        return self


def constraint_fit(job: JobCreate, criteria: SearchCriteria) -> ConstraintFit:
    unknown = False
    if criteria.work_types:
        if job.type_of_work == WorkType.UNKNOWN:
            unknown = True
        elif job.type_of_work not in criteria.work_types:
            return "violates"
    if criteria.max_hours_per_week is not None:
        if job.hours_per_week is None:
            unknown = True
        elif job.hours_per_week > criteria.max_hours_per_week:
            return "violates"
    return "unknown" if unknown else "meets"


class QueryGroup(DatasetModel):
    id: Slug
    split: Split
    criteria: SearchCriteria
    cases: list[EvaluationCase] = Field(min_length=2)

    @model_validator(mode="after")
    def check_constraints(self):
        for case in self.cases:
            expected = constraint_fit(case.job, self.criteria)
            if case.constraint_fit != expected:
                raise ValueError(f"{case.id}: constraint label conflicts with job facts")
            if expected == "violates" and case.relevance_grade != 0:
                raise ValueError(f"{case.id}: hard constraint violation must have grade 0")
            if expected == "unknown" and case.relevance_grade == 2:
                raise ValueError(f"{case.id}: unknown constraint cannot receive grade 2")
        return self


class EvaluationDataset(DatasetModel):
    schema_version: int = Field(ge=1, le=1, strict=True)
    dataset_id: Slug
    groups: list[QueryGroup] = Field(min_length=2)

    @model_validator(mode="after")
    def check_dataset(self):
        if {group.split for group in self.groups} != {"dev", "holdout"}:
            raise ValueError("both dev and holdout query groups are required")
        group_ids = [group.id for group in self.groups]
        cases = [case for group in self.groups for case in group.cases]
        ids = [case.id for case in cases]
        overviews = [normalized(case.job.job_overview) for case in cases]
        queries = [normalized(group.criteria.query) for group in self.groups]
        if len(set(group_ids)) != len(group_ids) or len(set(ids)) != len(ids):
            raise ValueError("group and case IDs must be unique")
        if len(set(overviews)) != len(overviews):
            raise ValueError("duplicate job overviews are not allowed")
        if "" in queries or len(set(queries)) != len(queries):
            raise ValueError("query groups must have nonblank, distinct queries")
        return self


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def load_dataset(path: Path = DEFAULT_PATH) -> EvaluationDataset:
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys,
                     parse_constant=_reject_constant)
    return EvaluationDataset.model_validate(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a local job-intelligence evaluation dataset.")
    parser.add_argument("path", type=Path, nargs="?", default=DEFAULT_PATH)
    args = parser.parse_args()
    try:
        dataset = load_dataset(args.path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"{dataset.dataset_id}: schema {dataset.schema_version}")
    for split in ("dev", "holdout"):
        groups = [group for group in dataset.groups if group.split == split]
        cases = [case for group in groups for case in group.cases]
        grades = Counter(case.relevance_grade for case in cases)
        poc_count = sum(case.poc is not None for case in cases)
        print(f"{split}: groups={len(groups)} jobs={len(cases)} "
              f"grades={dict(sorted(grades.items()))} fixed_pocs={poc_count}")


if __name__ == "__main__":
    main()