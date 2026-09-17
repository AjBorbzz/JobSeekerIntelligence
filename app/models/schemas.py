from datetime import date, datetime 
from enum import Enum 
from uuid import UUID 
from pydantic import BaseModel, Field 


class WorkType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    FREELANCE = "freelance"
    CONTRACT = "contract"
    UNKNOWN = "unknown"

# Data supplied by the user.
class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    source_url: str | None = None
    company: str | None = Field(default=None, max_length=200)
    type_of_work: WorkType = WorkType.UNKNOWN
    hours_per_week: float | None = Field(default=None, ge=0,le=168)
    salary: str | None = None 
    date_updated: date | None = None 
    job_overview: str = Field(min_length=20,)

# Job stored inside our application
class Job(JobCreate):
    id: UUID
    created_at: datetime


class SeniorityLevel(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"

class EvidenceCategory(str, Enum):
    REQUIRED_SKILL = "required_skill"
    PREFERRED_SKILL = "preferred_skill"
    TECH_STACK = "tech_stack"
    RESPONSIBILITY = "responsibility"
    PAIN_POINT = "pain_point"
    DELIVERABLE = "deliverable"
    SENIORITY = "seniority"
    BUSINESS_PROBLEM = "business_problem"

class AnalysisEvidence(BaseModel):
    category: EvidenceCategory
    claim: str = Field(min_length=2, max_length=300)
    source_text: str = Field(min_length=2, max_length=500)

class JobAnalysis(BaseModel):
    job_id: UUID
    role_category: str 
    role_summary: str 
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    required_skills: list[str] = Field(default_factory=list,)
    preferred_skills: list[str] = Field(default_factory=list,)
    tech_stack: list[str] = Field(default_factory=list,)
    responsibilities: list[str] = Field(default_factory=list,)
    employer_pain_points: list[str] = Field(default_factory=list,)
    business_problem: str | None = None
    expected_deliverables: list[str] = Field(default_factory=list,)
    evidence: list[AnalysisEvidence] = Field(default_factory=list,)