from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class POCProposalSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: UUID
    request: dict[str, Any]
    analysis: dict[str, Any]
    proposal: dict[str, Any]
    saved_at: datetime
    schema_version: Literal[1]

    @model_validator(mode="after")
    def validate_job_ids(self) -> Self:
        for name, payload in (("analysis", self.analysis), ("proposal", self.proposal)):
            if payload.get("job_id") != str(self.job_id):
                raise ValueError(f"Stored {name} belongs to a different job or has no job_id")

        return self