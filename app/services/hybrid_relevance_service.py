from app.models.schemas import (
    HybridRelevance,
    Job,
    JobAnalysis,
    RelevanceComponent,
    SearchCriteria,
)
from app.scoring.hybrid_relevance import (
    constraint_score,
    role_match_score,
    skill_match_score,
    weighted_score,
)
from app.services.relevance_service import RelevanceService


class HybridRelevanceService:
    SEMANTIC_WEIGHT = 0.50
    ROLE_WEIGHT = 0.20
    SKILL_WEIGHT = 0.20
    CONSTRAINT_WEIGHT = 0.10

    def __init__(self, semantic_service: RelevanceService | None = None):
        self.semantic_service = semantic_service or RelevanceService()

    def calculate(self, criteria: SearchCriteria, job: Job, analysis: JobAnalysis) -> HybridRelevance:
        semantic = self.semantic_service.calculate_semantic_relevance(
            query=criteria.query,
            job=job,
            analysis=analysis,
        )

        role_score, role_details = role_match_score(criteria.query, job, analysis)
        skill_score, skill_details = skill_match_score(criteria, analysis)
        work_score, constraint_notes = constraint_score(criteria, job)

        components: list[RelevanceComponent] = [
            RelevanceComponent(
                name="semantic",
                score=semantic.semantic_score,
                weight=self.SEMANTIC_WEIGHT,
                details=[f"Cosine similarity: {semantic.cosine_similarity:.6f}"],
            ),
            RelevanceComponent(
                name="role",
                score=role_score,
                weight=self.ROLE_WEIGHT,
                details=role_details,
            ),
        ]

        weighted_components = [
            (semantic.semantic_score, self.SEMANTIC_WEIGHT),
            (role_score, self.ROLE_WEIGHT),
        ]

        if skill_score is not None:
            components.append(
                RelevanceComponent(
                    name="skills",
                    score=skill_score,
                    weight=self.SKILL_WEIGHT,
                    details=[
                        f"Matched required skills: {', '.join(skill_details['matched_required']) or 'none'}",
                        f"Missing required skills: {', '.join(skill_details['missing_required']) or 'none'}",
                        f"Matched preferred skills: {', '.join(skill_details['matched_preferred']) or 'none'}",
                    ],
                )
            )
            weighted_components.append((skill_score, self.SKILL_WEIGHT))

        if work_score is not None:
            components.append(
                RelevanceComponent(
                    name="constraints",
                    score=work_score,
                    weight=self.CONSTRAINT_WEIGHT,
                    details=constraint_notes,
                )
            )
            weighted_components.append((work_score, self.CONSTRAINT_WEIGHT))

        return HybridRelevance(
            job_id=job.id,
            query=criteria.query,
            overall_score=weighted_score(weighted_components),
            components=components,
            matched_required_skills=skill_details["matched_required"],
            missing_required_skills=skill_details["missing_required"],
            matched_preferred_skills=skill_details["matched_preferred"],
            missing_preferred_skills=skill_details["missing_preferred"],
            constraint_notes=constraint_notes,
        )


hybrid_relevance_service = HybridRelevanceService()