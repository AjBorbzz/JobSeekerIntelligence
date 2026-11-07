from fastapi import APIRouter, HTTPException, Response

from app.models.collection import (
    GreenhouseImportRequest, GreenhouseImportResponse, GreenhouseSearchRequest, GreenhouseSearchResponse,
)
from app.services.greenhouse_service import greenhouse_service
from app.sources.greenhouse_client import CollectionError

router = APIRouter(prefix="/jobs", tags=["job collection"])


def provider_error(exc: CollectionError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    return HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers)


@router.post("/search/greenhouse", response_model=GreenhouseSearchResponse)
def search_greenhouse(request: GreenhouseSearchRequest) -> GreenhouseSearchResponse:
    try:
        return greenhouse_service.search(request)
    except CollectionError as exc:
        raise provider_error(exc) from exc


@router.post("/import/greenhouse", response_model=GreenhouseImportResponse, status_code=201)
def import_greenhouse(request: GreenhouseImportRequest, response: Response) -> GreenhouseImportResponse:
    try:
        result = greenhouse_service.import_job(request)
    except CollectionError as exc:
        raise provider_error(exc) from exc
    response.status_code = 201 if result.created else 200
    return result