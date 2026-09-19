from app.embeddings.client import EmbeddingClient

from app.models.schemas import (
    Job, 
    JobAnalysis,
    SemanticRelevance,
)

from app.scoring.semantic_relevance import (
    cosine_similarity,
    similarity_to_score,
)

class RelevanceService:
    def __init__(self, embedding_client: EmbeddingClient | None = None):
        self.embedding_client = (embedding_client or EmbeddingClient())

    def build_job_document(self, job: Job, analysis: JobAnalysis,) -> str:
        sections: list[str] = [
            f"Job Title: {job.title}",
            f"Role Category: {analysis.role_category}",
            f"Role Summary: {analysis.role_summary}" 
        ]

        if analysis.required_skills:
            sections.append("Required skills: " + ", ".join(analysis.required_skills))

        if analysis.preferred_skills:
            sections.append("Preferred Skills:" + ", ".join(analysis.preferred_skills))

        if analysis.tech_stack:
            sections.append("Technology stack: " + ", ".join(analysis.tech_stack))

        if analysis.responsibilities:
            sections.append("Responsibilities: " + "; ".join(analysis.responsibilities))

        if analysis.business_problem:
            sections.append("Business problem: " + analysis.business_problem)

        return "\n".join(sections)

    def calculate_semantic_relevance(self,query: str, job: Job, analysis: JobAnalysis,) -> SemanticRelevance:
        query = query.strip()

        if not query:
            raise ValueError("Search query cannot be empty.")

        job_document = self.build_job_document(job=job, analysis=analysis,)

        embeddings = (self.embedding_client.embed_batch([query, job_document,]))

        query_embedding = embeddings[0]
        job_embedding = embeddings[1]

        similarity = cosine_similarity(query_embedding,job_embedding,)

        return SemanticRelevance(
            job_id=job.id,
            query=query,
            embedding_model=(self.embedding_client.model),
            cosine_similarity=round(similarity,6,),
            semantic_score=similarity_to_score(similarity),
        )

relevance_service = RelevanceService()