from uuid import UUID

from app.llm.poc_evaluator import POCEvaluator, proposal_evidence
from app.models.schemas import (
    JobAnalysis, POCCoverageComponent, POCCoverageStatus, POCEvaluation,
    POCEvaluationData, POCProposal, POCRequirement, POCRequirementType,
)
from app.repositories.poc_evaluation_repository import POCEvaluationRepository

REQUIREMENT_WEIGHTS = {
    POCRequirementType.REQUIRED_SKILL: 0.35,
    POCRequirementType.RESPONSIBILITY: 0.25,
    POCRequirementType.PAIN_POINT: 0.15,
    POCRequirementType.DELIVERABLE: 0.15,
    POCRequirementType.BUSINESS_PROBLEM: 0.10,
}
STATUS_POINTS = {
    POCCoverageStatus.COVERED: 1.0,
    POCCoverageStatus.PARTIAL: 0.5,
    POCCoverageStatus.MISSING: 0.0,
}


class POCEvaluationError(ValueError):
    pass


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def unique_texts(texts: list[str]) -> list[str]:
    seen = set()
    result = []
    for text in texts:
        cleaned = " ".join(text.split())
        key = normalize(cleaned)
        if key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def build_requirements(analysis: JobAnalysis) -> list[POCRequirement]:
    groups = {
        POCRequirementType.REQUIRED_SKILL: analysis.required_skills,
        POCRequirementType.RESPONSIBILITY: analysis.responsibilities,
        POCRequirementType.PAIN_POINT: analysis.employer_pain_points,
        POCRequirementType.DELIVERABLE: analysis.expected_deliverables,
        POCRequirementType.BUSINESS_PROBLEM: [analysis.business_problem] if analysis.business_problem else [],
    }
    return [
        POCRequirement(id=f"{kind.value}:{index}", requirement_type=kind, text=text)
        for kind, texts in groups.items()
        for index, text in enumerate(unique_texts(texts), start=1)
    ]


def validate_assessment(requirements: list[POCRequirement], proposal: POCProposal, data: POCEvaluationData) -> None:
    expected = {item.id for item in requirements}
    returned = [item.requirement_id for item in data.requirement_evaluations]
    if len(returned) != len(set(returned)):
        raise POCEvaluationError("Evaluator returned duplicate requirement IDs")
    if set(returned) != expected:
        raise POCEvaluationError("Evaluator must return every expected requirement ID and no unknown IDs")
    if not data.summary.strip():
        raise POCEvaluationError("Evaluator summary cannot be empty")

    sources = proposal_evidence(proposal)
    for item in data.requirement_evaluations:
        if not item.explanation.strip():
            raise POCEvaluationError(f"Empty explanation for {item.requirement_id}")
        if item.status == POCCoverageStatus.MISSING:
            if item.project_evidence:
                raise POCEvaluationError(f"Missing requirement has contradictory evidence: {item.requirement_id}")
            continue
        if not item.project_evidence:
            raise POCEvaluationError(f"Covered or partial requirement needs evidence: {item.requirement_id}")
        for quote in item.project_evidence:
            if not quote.strip() or not any(quote.strip() in source for source in sources):
                raise POCEvaluationError(f"Evidence is not copied from the proposal: {item.requirement_id}")


class POCEvaluationService:
    def __init__(self, evaluator: POCEvaluator | None = None, repository: POCEvaluationRepository | None = None):
        self.evaluator = evaluator if evaluator is not None else POCEvaluator()
        self.repository = repository if repository is not None else POCEvaluationRepository()

    def evaluate(self, analysis: JobAnalysis, proposal: POCProposal) -> POCEvaluation:
        if analysis.job_id != proposal.job_id:
            raise POCEvaluationError("Analysis and proposal belong to different jobs")
        requirements = build_requirements(analysis)
        if not requirements:
            raise POCEvaluationError("Analysis has no evaluable requirements")

        data = POCEvaluationData.model_validate(self.evaluator.evaluate(requirements, proposal))
        validate_assessment(requirements, proposal, data)
        by_id = {item.requirement_id: item for item in data.requirement_evaluations}
        active = {item.requirement_type for item in requirements}
        denominator = sum(REQUIREMENT_WEIGHTS[kind] for kind in active)
        components = []
        requirement_score = 0.0

        for kind, base_weight in REQUIREMENT_WEIGHTS.items():
            group = [item for item in requirements if item.requirement_type == kind]
            if not group:
                continue
            statuses = [by_id[item.id].status for item in group]
            score = 100.0 * sum(STATUS_POINTS[status] for status in statuses) / len(statuses)
            weight = base_weight / denominator
            requirement_score += weight * score
            components.append(POCCoverageComponent(
                requirement_type=kind, score=round(score, 2), weight=weight,
                covered=statuses.count(POCCoverageStatus.COVERED),
                partial=statuses.count(POCCoverageStatus.PARTIAL),
                missing=statuses.count(POCCoverageStatus.MISSING),
            ))

        skills = unique_texts(analysis.required_skills)
        declared = set(normalize(text) for text in proposal.tech_stack)
        for component in proposal.architecture:
            declared.update(normalize(text) for text in component.technologies)
        matched = [skill for skill in skills if normalize(skill) in declared]
        missing = [skill for skill in skills if normalize(skill) not in declared]
        skill_score = 100.0 * len(matched) / len(skills) if skills else None
        overall = requirement_score if skill_score is None else 0.8 * requirement_score + 0.2 * skill_score

        return POCEvaluation(
            job_id=analysis.job_id, project_name=proposal.project_name, evaluated_by=self.evaluator.model,
            requirement_coverage_score=round(requirement_score, 2),
            explicit_skill_coverage_score=round(skill_score, 2) if skill_score is not None else None,
            poc_relevance_score=round(overall, 2), coverage_components=components,
            matched_required_skills=matched, missing_required_skills=missing,
            requirement_evaluations=[by_id[item.id] for item in requirements],
            strengths=data.strengths, gaps=data.gaps, unnecessary_complexity=data.unnecessary_complexity,
            summary=data.summary,
        )

    def get(self, job_id: UUID) -> POCEvaluation | None:
        snapshot = self.repository.get_latest(job_id)
        return POCEvaluation.model_validate(snapshot.evaluation) if snapshot is not None else None


poc_evaluation_service = POCEvaluationService()
