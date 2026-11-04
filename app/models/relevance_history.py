from datetime import datetime 
from typing import Any, Literal
from uuid import UUID 

from pydantic import BaseModel, ConfigDict 

RelevanceKind = Literal["semantic", "hybrid"]

class RelevanceRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: UUID 
    kind: RelevanceKind
    criteria: dict[str, Any]
    result: dict[str, Any]
    saved_at: datetime 
    schema_version: Literal[1]