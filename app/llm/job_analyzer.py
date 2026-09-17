from app.llm.client import OllamaClient
from app.models.schemas import Job, JobAnalysis


SYSTEM_PROMPT = """
You are a job intelligence analyst.

Your task is to analyze job advertisements accurately.

Rules:

1. Only use information found in the supplied job advertisement.
2. Do not invent technologies, responsibilities, qualifications,
   business problems, or requirements.
3. Distinguish required skills from preferred or optional skills.
4. Distinguish technologies merely mentioned as part of an existing
   system from technologies the applicant is expected to use.
5. Employer pain points must represent problems the employer appears
   to be trying to solve.
6. If a business problem is not clear, return null.
7. If seniority cannot be determined reliably, return "unknown".
8. Evidence source_text must be copied directly from the supplied
   job overview.
9. Keep source_text evidence concise.
10. Do not infer requirements merely because they are common for
    the role.
"""


class JobAnalyzer:
    def __init__(self,client: OllamaClient | None = None,):
        self.client = client or OllamaClient(model="gemma4:12b")

    def analyze(self,job: Job,) -> JobAnalysis:
        prompt = f"""
                    Analyze the following job advertisement.

                    JOB ID:
                    {job.id}

                    JOB TITLE:
                    {job.title}

                    COMPANY:
                    {job.company or "Not provided"}

                    TYPE OF WORK:
                    {job.type_of_work.value}

                    HOURS PER WEEK:
                    {job.hours_per_week or "Not provided"}

                    SALARY:
                    {job.salary or "Not provided"}

                    JOB OVERVIEW:
                    ---
                    {job.job_overview}
                    ---

                    Identify:

                    - actual role category
                    - concise role summary
                    - seniority
                    - required skills
                    - preferred skills
                    - technologies explicitly mentioned
                    - responsibilities
                    - employer pain points
                    - underlying business problem
                    - expected deliverables

                    For every important interpretation, provide evidence using text copied
                    directly from the job overview.

                    Do not add skills or technologies merely because they are normally
                    associated with this job title.
                    """

        return self.client.generate_structured(prompt=prompt,
            schema=JobAnalysis,
            system_prompt=SYSTEM_PROMPT,
        )