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

class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    source_url: str | None = None
    company: str | None = Field(default=None, max_length=200)
    type_of_work: WorkType = WorkType.UNKNOWN
    hours_per_week: float | None = Field(default=None, ge=0,le=168)
    salary: str | None = None 
    date_updated: date | None = None 
    job_overview: str = Field(min_length=20,)

class Job(JobCreate):
    id: UUID
    created_at: datetime
    