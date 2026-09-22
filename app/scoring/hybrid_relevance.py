import re 

from app.models.schemas import Job, JobAnalysis, SearchCriteria 

SKILL_ALIASES = {
    "fast api": "fastapi",
    "postgres": "postgresql",
    "postgres sql": "postgresql",
    "restful api": "restapi",
    "restful apis": "restapi",
    "rest apis": "restapi",
    "llms": "llm"
}

def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9+#.\s-]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def normalize_skill(skill: str) -> str:
    normalized = normalize_text(skill)
    return SKILL_ALIASES.get(normalized, normalized)

def role_match_score(query: str, job: Job, analysis: JobAnalysis) -> tuple[float, list[str]]:
    query_tokens = set(normalize_text(query).split())

    if not query_tokens:
        return 0.0, ["Search query contains no usable tokens."]

    role_text = " ".join([job.title, analysis.role_category, analysis.role_summary])

    role_tokens = set(normalize_text(role_text).split())
    matched = sorted(query_tokens & role_tokens)
    score = len(matched) / len(query_tokens) * 100

    details = [
        f"Matched query tokens: {', '.join(matched)}" if matched else "No direct query-token match."
    ]
    return round(score, 2), details

def skill_match_score(criteria: SearchCriteria, analysis: JobAnalysis) -> tuple[float | None, dict[str, list[str]]]:
    requested_required = [normalize_skill(skill) for skill in criteria.required_skills]
    requested_preferred = [normalize_skill(skill) for skill in criteria.preferred_skills]

    if not requested_required and not requested_preferred:
        return None, {
            "matched_required": [],
            "missing_required": [],
            "matched_preferred": [],
            "matched_preferred": [],
        }

    job_skills = {
        normalize_skill(skill)
        for skill in (
            analysis.required_skills
            + analysis.preferred_skills
            + analysis.tech_stack
            )
    }

    matched_required = [skill for skill in requested_required if skill in job_skills]
    missing_required = [skill for skill in requested_required if skill not in job_skills]

    matched_preferred = [skill for skill in requested_preferred if skill in job_skills]
    missing_preferred = [skill for skill in requested_preferred if skill not in job_skills]

    scores = []
    weights = []

    if requested_required:
        scores.append(len(matched_required) / len(requested_required) * 100)
        weights.append(0.8)

    if requested_preferred:
        scores.append(len(matched_preferred) / len(requested_preferred) * 100)
        weights.append(0.2 if requested_required else 1.0)

    score = sum(score * weight for score, weight in zip(scores, weights)) / sum(weights)

    return round(score, 2), {
        "matched_required": matched_required,
        "missing_required": missing_required,
        "matched_preferred": matched_preferred,
        "missing_preferred": missing_preferred
    }

def constraint_score(criteria: SearchCriteria, job: Job) -> tuple[float | None, list[str]]:
    checks: list[float] = []
    notes: list[str] = []

    if criteria.work_types:
        if job.type_of_work in criteria.work_types:
            checks.append(100.0)
            notes.append(f"Work type matches: {job.type_of_work.value}.")

        elif job.type_of_work.value == "unknown":
            checks.append(50.0)
            notes.append("Job work type is unknown.")

        else:
            checks.append(0.0)
            notes.append(f"Work type does not match: {job.type_of_work.value}.")

    if criteria.max_hours_per_week is not None:
        if job.hours_per_week is None:
            checks.append(50.0)
            notes.append("Hours per week were not provided.")
        elif job.hours_per_week <= criteria.max_hours_per_week:
            checks.append(100.0)
            notes.append(
                f"Hours requirement matches: {job.hours_per_week:g} <="
                f"{criteria.max_hours_per_week:g}." 
            )

        else:
            checks.append(0.0)
            notes.append(
                f"Hours exceed requested maximum : {job.hours_per_week:g}"
                f"{criteria.max_hours_per_week:g}"
            )

    if not checks:
        return None, []

    return round(sum(checks) / len(checks), 2), notes


def weighted_score(components: list[tuple[float, float]]) -> float:
    if not components:
        return 0.0 

    weighted_sum = sum(score * weight for score, weight in components)
    active_weight = sum(weight for _, weight in components)

    return round(weighted_sum / active_weight, 2)