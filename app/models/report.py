from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.schemas import Job, JobAnalysis, POCEvaluation, POCGenerationRequest, POCProposal


class ReportNotFound(LookupError):
    pass


class ReportDataError(ValueError):
    pass


class ReportTooLarge(ValueError):
    pass


class ReportSnapshot(BaseModel):
    generated_at: datetime
    job: Job
    analysis: JobAnalysis | None = None
    analysis_origin: Literal["proposal_snapshot", "latest_saved_analysis", "missing"] = "missing"
    latest_analysis_saved_at: datetime | None = None
    request: POCGenerationRequest | None = None
    proposal: POCProposal | None = None
    proposal_id: int | None = None
    proposal_saved_at: datetime | None = None
    evaluation: POCEvaluation | None = None
    evaluation_id: int | None = None
    evaluation_saved_at: datetime | None = None