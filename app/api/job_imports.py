from fastapi import APIRouter, HTTPException, status

from app.models.job_import import HtmlJobImportRequest, HtmlJobImportResponse
from app.services.job_import_service import job_import_service
from app.sources.base import JobSourceError

router = APIRouter(prefix="/jobs", tags=["job imports"])


@router.post("/from-html", response_model=HtmlJobImportResponse, status_code=status.HTTP_201_CREATED)
def import_html_job(request: HtmlJobImportRequest) -> HtmlJobImportResponse:
    try:
        return job_import_service.import_html(request)
    except JobSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc