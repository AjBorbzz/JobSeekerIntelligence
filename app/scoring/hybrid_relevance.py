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