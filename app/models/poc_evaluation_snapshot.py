from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class POCEvaluationSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposal_id: int
    evaluation: dict[str, Any]
    saved_at: datetime
    schema_version: Literal[1]