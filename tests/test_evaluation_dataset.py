import json

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import (
    DEFAULT_PATH, EvaluationDataset, constraint_fit, load_dataset, requirement_keys,
)
from app.models.schemas import JobCreate, SearchCriteria


@pytest.fixture
def raw():
    return json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))


def first_case(raw):
    return raw["groups"][0]["cases"][0]


def test_starter_fixture():
    dataset = load_dataset()
    assert dataset.dataset_id == "synthetic-v1"
    assert {group.split for group in dataset.groups} == {"dev", "holdout"}
    assert sum(len(group.cases) for group in dataset.groups) == 8
    for group in dataset.groups:
        assert sorted(case.relevance_grade for case in group.cases) == [0, 0, 1, 2]
        poc_cases = [case for case in group.cases if case.poc is not None]
        assert len(poc_cases) == 1
        case = poc_cases[0]
        assert len(requirement_keys(case.analysis_gold)) == 4
        assert {item.status.value for item in case.poc.coverage} == {"covered", "partial", "missing"}


def test_untrusted_text_is_not_a_gold_skill():
    dataset = load_dataset()
    case = next(case for group in dataset.groups for case in group.cases if case.id == "holdout-04")
    assert "Kubernetes" in case.job.job_overview
    assert "Kubernetes" in case.forbidden_skills
    assert case.analysis_gold.required_skills == ["Figma"]


@pytest.mark.parametrize(
    "work_type,hours,types,cap,expected",
    [
        ("part_time", 20, ["part_time"], 20, "meets"),
        ("part_time", 20.5, ["part_time"], 20, "violates"),
        ("full_time", None, ["part_time"], 20, "violates"),
        ("unknown", 25, ["part_time"], 20, "violates"),
        ("unknown", 20, ["part_time"], 20, "unknown"),
        ("part_time", None, ["part_time"], 20, "unknown"),
        ("unknown", None, [], None, "meets"),
        ("part_time", None, ["part_time"], None, "meets"),
    ],
)
def test_constraints(work_type, hours, types, cap, expected):
    job = JobCreate(
        title="Example listing", type_of_work=work_type, hours_per_week=hours,
        job_overview="A synthetic example for evaluating schedule facts.",
    )
    criteria = SearchCriteria(query="Example query", work_types=types, max_hours_per_week=cap)
    assert constraint_fit(job, criteria) == expected


def test_rejects_unsupported_schema_version(raw):
    raw["schema_version"] = 2
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(raw)


def test_rejects_duplicate_case_id(raw):
    raw["groups"][1]["cases"][0]["id"] = first_case(raw)["id"]
    with pytest.raises(ValidationError, match="IDs must be unique"):
        EvaluationDataset.model_validate(raw)


def test_rejects_duplicate_source_across_splits(raw):
    raw["groups"][1]["cases"][0] = {**first_case(raw), "id": "copied-holdout"}
    raw["groups"][1]["cases"][0]["constraint_fit"] = "meets"
    with pytest.raises(ValidationError, match="duplicate job overviews"):
        EvaluationDataset.model_validate(raw)


def test_rejects_missing_split(raw):
    raw["groups"][1]["split"] = "dev"
    with pytest.raises(ValidationError, match="both dev and holdout"):
        EvaluationDataset.model_validate(raw)


def test_rejects_fabricated_source_quote(raw):
    first_case(raw)["analysis_gold"]["evidence"][0]["source_text"] = "A quote not in the listing."
    with pytest.raises(ValidationError, match="exact job overview quote"):
        EvaluationDataset.model_validate(raw)


def test_rejects_missing_skill_evidence(raw):
    first_case(raw)["analysis_gold"]["evidence"].pop(0)
    with pytest.raises(ValidationError, match="missing evidence for required_skill"):
        EvaluationDataset.model_validate(raw)


def test_rejects_missing_seniority_evidence(raw):
    first_case(raw)["analysis_gold"]["evidence"].pop()
    with pytest.raises(ValidationError, match="known seniority requires evidence"):
        EvaluationDataset.model_validate(raw)


def test_rejects_forbidden_skill_overlap(raw):
    first_case(raw)["forbidden_skills"] = ["  PYTHON  "]
    with pytest.raises(ValidationError, match="overlapping"):
        EvaluationDataset.model_validate(raw)


def test_rejects_conflicting_constraint_label(raw):
    first_case(raw)["constraint_fit"] = "unknown"
    with pytest.raises(ValidationError, match="constraint label conflicts"):
        EvaluationDataset.model_validate(raw)


@pytest.mark.parametrize(
    "group_index,case_index,grade,reason",
    [
        (0, 2, 1, "hard constraint violation"),
        (1, 1, 2, "unknown constraint"),
    ],
)
def test_rejects_grade_that_overstates_fit(raw, group_index, case_index, grade, reason):
    raw["groups"][group_index]["cases"][case_index]["relevance_grade"] = grade
    with pytest.raises(ValidationError, match=reason):
        EvaluationDataset.model_validate(raw)


def test_rejects_missing_poc_requirement_label(raw):
    first_case(raw)["poc"]["coverage"].pop()
    with pytest.raises(ValidationError, match="every gold requirement exactly once"):
        EvaluationDataset.model_validate(raw)


def test_rejects_fabricated_poc_evidence(raw):
    first_case(raw)["poc"]["coverage"][0]["project_evidence"] = ["Not in any proposed feature."]
    with pytest.raises(ValidationError, match="quote a feature description exactly"):
        EvaluationDataset.model_validate(raw)


def test_rejects_evidence_for_missing_poc_coverage(raw):
    first_case(raw)["poc"]["coverage"][-1]["project_evidence"] = ["Python"]
    with pytest.raises(ValidationError, match="missing coverage cannot carry evidence"):
        EvaluationDataset.model_validate(raw)


@pytest.mark.parametrize(
    "content,reason",
    [
        ('{"schema_version": 1, "schema_version": 2}', "Duplicate JSON key"),
        ('{"schema_version": NaN}', "Non-finite JSON constant"),
    ],
)
def test_rejects_ambiguous_json(tmp_path, content, reason):
    file = tmp_path / "invalid.json"
    file.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        load_dataset(file)