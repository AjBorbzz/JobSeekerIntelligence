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