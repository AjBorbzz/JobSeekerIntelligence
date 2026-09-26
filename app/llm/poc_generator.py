from app.llm.client import OllamaClient 
from app.models.schemas import (
    HybridRelevance,
    Job,
    JobAnalysis,
    POCComplexity,
    POCProposalData,
    SearchCriteria,
)

SYSTEM_PROMPT = """
You are a senior software engineer designing small proof-of-concept projects
for technical job interviews.

Your task is to design the smallest useful project that demonstrates the
important technical capabilities requested by the employer.

Rules:

1. Base the project primarily on the supplied job analysis.
2. Do not invent employer requirements.
3. Prioritize required skills, responsibilities, pain points, and expected
   deliverables.
4. Preferred skills may be included when they improve the demonstration.
5. Technologies merely mentioned as part of an existing system should not
   automatically become project requirements.
6. Keep the project deliberately small.
7. Do not design a production platform.
8. Do not add authentication, Kubernetes, microservices, queues, cloud
   infrastructure, CI/CD, or other infrastructure unless directly relevant.
9. Supporting libraries may be introduced only when necessary to implement
   the requested capability.
10. Each major feature must explain why it is relevant to the job.
11. The demo scenario must be concrete and easy to demonstrate.
12. Acceptance criteria must be objectively testable.
13. Explicitly identify functionality that is out of scope.
14. Do not score or evaluate your own project.
"""

class POCGenerator:
    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient(model="gemma4:12b")

    def generator(
            self,
            job: Job,
            analysis: JobAnalysis,
            criteria: SearchCriteria,
            relevance: HybridRelevance,
            max_complexity: POCComplexity,
    ) -> POCProposalData:

        relevance_components = "\n".join(f"- {component.name}: {component.score:.2f}/100"
                                         for component in relevance.components
                                         )

        prompt = f"""
            Design a proof-of-concept project for the following job.

            JOB TITLE:
            {job.title}

            ROLE CATEGORY:
            {analysis.role_category}

            ROLE SUMMARY:
            {analysis.role_summary}

            SENIORITY:
            {analysis.seniority.value}

            REQUIRED SKILLS:
            {", ".join(analysis.required_skills) or "None explicitly identified"}

            PREFERRED SKILLS:
            {", ".join(analysis.preferred_skills) or "None explicitly identified"}

            TECHNOLOGY STACK:
            {", ".join(analysis.tech_stack) or "None explicitly identified"}

            RESPONSIBILITIES:
            {chr(10).join(f"- {item}" for item in analysis.responsibilities) or "None"}

            EMPLOYER PAIN POINTS:
            {chr(10).join(f"- {item}" for item in analysis.employer_pain_points) or "None"}

            BUSINESS PROBLEM:
            {analysis.business_problem or "Not clearly identified"}

            EXPECTED DELIVERABLES:
            {chr(10).join(f"- {item}" for item in analysis.expected_deliverables) or "None"}

            USER SEARCH:
            {criteria.query}

            CURRENT RELEVANCE:
            {relevance.overall_score:.2f}/100

            RELEVANCE COMPONENTS:
            {relevance_components}

            MAXIMUM PROJECT COMPLEXITY:
            {max_complexity.value}

            Create a project that could be demonstrated during a technical interview
            or included in a portfolio repository.

            Prefer one coherent workflow over many unrelated features.

            Do not create features solely to increase the number of technologies used.
            """

        return self.client.generate_structured(
            prompt=prompt,
            schema=POCProposalData,
            system_prompt=SYSTEM_PROMPT,
        )

    