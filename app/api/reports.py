from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.models.report import ReportDataError, ReportNotFound, ReportTooLarge
from app.services.report_service import report_service

router = APIRouter(prefix="/jobs", tags=["reports"])

@router.get("/{job_id}/report.pdf", response_class=Response, responses={
    200: {"content": {"application/pdf": {}}, "description": "Saved job intelligence PDF"},
})
def download_report(job_id: UUID, proposal_id: Annotated[int | None, Query(ge=1)] = None) -> Response:
    try:
        content, filename = report_service.export(job_id, proposal_id)
    except ReportNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReportDataError as exc:
        raise HTTPException(409, "Stored report data is invalid or incompatible; repair the record before export.") from exc
    except ReportTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })