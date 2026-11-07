import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.job_collection import router
from app.db.models import ExternalJobIdentity, JobRecord
from app.models.collection import GreenhouseImportRequest, GreenhouseSearchRequest
from app.repositories.external_job_repository import ExternalJobRepository
from app.services.greenhouse_service import GreenhouseService, greenhouse_service
from app.sources.base import JobSourceError
from app.sources.greenhouse_client import CollectionError, GreenhouseClient, retry_delay
from app.sources.greenhouse_mapping import normalize_post


def post(job_id=101, **updates):
    return {
        "id": job_id, "internal_job_id": 1000 + job_id, "title": "Python Backend Developer",
        "content": "&lt;p&gt;Build reliable Python APIs with FastAPI and PostgreSQL.&lt;/p&gt;",
        "updated_at": "2026-11-07T09:00:00Z",
        "absolute_url": f"https://careers.example/jobs/{job_id}",
        "location": {"name": "Remote"},
        **updates,
    }


class Clock:
    now = 1.0

    def __call__(self):
        return self.now


def client_for(handler, **kwargs):
    return GreenhouseClient(transport=httpx.MockTransport(handler), min_interval=0, **kwargs)


def test_fixed_endpoint_is_get_without_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"jobs": [post()]})

    client = client_for(handler)
    payload, cached = client.fetch("example_board")
    assert payload["jobs"][0]["id"] == 101
    assert not cached
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == "https://boards-api.greenhouse.io/v1/boards/example_board/jobs?content=true"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


def test_detail_request_uses_post_id():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=post())

    client_for(handler).fetch("example", 101)
    assert seen == ["https://boards-api.greenhouse.io/v1/boards/example/jobs/101"]


@pytest.mark.parametrize("board", ["../admin", "https://example.com", "bad/token", "a?x=1", "a" * 81])
def test_bad_board_cannot_construct_a_request(board):
    client = client_for(lambda request: pytest.fail("No request expected"))
    with pytest.raises(CollectionError) as exc:
        client.fetch(board)
    assert exc.value.status_code == 422


def test_cache_is_defensive_and_expires():
    calls = []
    clock = Clock()
    client = client_for(lambda request: calls.append(request) or httpx.Response(200, json={"jobs": [post()]}), clock=clock)
    data, _ = client.fetch("example")
    data["jobs"].clear()
    cached, hit = client.fetch("example")
    assert hit and cached["jobs"]
    assert len(calls) == 1
    clock.now += 301
    assert client.fetch("example")[1] is False
    assert len(calls) == 2


def test_lru_cache_has_a_bounded_entry_count():
    client = client_for(lambda request: httpx.Response(200, json={"jobs": []}))
    for index in range(10):
        client.fetch(f"board{index}")
    assert len(client._cache) == 8


def test_local_pacing_returns_retry_after_without_sleep():
    clock = Clock()
    client = GreenhouseClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": []})), clock=clock,
    )
    client.fetch("one")
    with pytest.raises(CollectionError) as exc:
        client.fetch("two")
    assert exc.value.status_code == 429
    assert exc.value.retry_after == 2


def test_upstream_429_sets_a_shared_cooldown():
    calls = []
    clock = Clock()
    client = client_for(
        lambda request: calls.append(request) or httpx.Response(429, headers={"Retry-After": "15"}),
        clock=clock,
    )
    with pytest.raises(CollectionError) as first:
        client.fetch("example")
    assert first.value.retry_after == 15
    clock.now += 1
    with pytest.raises(CollectionError) as second:
        client.fetch("other")
    assert second.value.retry_after == 14
    assert len(calls) == 1


def test_retry_after_http_date_and_fallback(monkeypatch):
    from app.sources import greenhouse_client as module
    monkeypatch.setattr(module.time, "time", lambda: 0)
    assert retry_delay("Thu, 01 Jan 1970 00:01:00 GMT") == 60
    assert retry_delay("nonsense") == 60
    assert retry_delay(None) == 60


@pytest.mark.parametrize("upstream,expected", [(401, 403), (403, 403), (404, 404), (500, 502), (302, 502)])
def test_upstream_failures_and_redirects_are_not_followed(upstream, expected):
    calls = []
    client = client_for(lambda request: calls.append(request) or httpx.Response(
        upstream, headers={"Location": "https://another.example/"},
    ))
    with pytest.raises(CollectionError) as exc:
        client.fetch("example")
    assert exc.value.status_code == expected
    assert len(calls) == 1


def test_timeout_is_distinct_from_other_connection_failure():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(CollectionError) as exc:
        client_for(timeout).fetch("example")
    assert exc.value.status_code == 504


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"bad":NaN}'])
def test_unreadable_provider_json_is_rejected(body):
    with pytest.raises(CollectionError) as exc:
        client_for(lambda request: httpx.Response(200, content=body)).fetch("example")
    assert exc.value.status_code == 502


def test_response_byte_limit_is_enforced():
    client = client_for(lambda request: httpx.Response(200, content=b"x" * 200), max_bytes=100)
    with pytest.raises(CollectionError, match="size limit"):
        client.fetch("example")


def test_normalization_handles_encoded_html_and_updated_date():
    candidate = normalize_post(post(company_name="Example Company"))
    assert candidate.data.title == "Python Backend Developer"
    assert candidate.data.job_overview == "Build reliable Python APIs with FastAPI and PostgreSQL."
    assert candidate.data.date_updated == date(2026, 11, 7)
    assert candidate.data.company == "Example Company"
    assert candidate.data.salary is None
    assert candidate.data.hours_per_week is None
    assert candidate.data.type_of_work.value == "unknown"
    assert candidate.location == "Remote"


def test_company_is_not_inferred_from_a_token_or_location():
    assert normalize_post(post()).data.company is None


@pytest.mark.parametrize("updates", [{"id": True}, {"title": ""}, {"content": "short"}, {"internal_job_id": None}])
def test_invalid_or_prospect_posts_are_not_jobs(updates):
    with pytest.raises(JobSourceError):
        normalize_post(post(**updates))


def test_bad_date_is_reported_without_inventing_one():
    candidate = normalize_post(post(updated_at="not-a-date"))
    assert candidate.data.date_updated is None
    assert candidate.warnings


@pytest.fixture
def repository(job_sessions):
    return ExternalJobRepository(job_sessions)


def test_search_is_preview_only_and_applies_a_local_query(repository, job_sessions):
    feed = {"jobs": [
        post(), post(102, title="Go Developer", content="Build APIs using Go and Kubernetes."),
        {"id": 500, "internal_job_id": None},
    ]}
    service = GreenhouseService(client=client_for(lambda request: httpx.Response(200, json=feed)), repository=repository)
    result = service.search(GreenhouseSearchRequest(board_token="example", query="Python FastAPI"))
    assert [x.external_id for x in result.candidates] == [101]
    assert result.fetched_count == 3
    assert result.matched_count == 1
    assert result.warnings
    with job_sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_limit_is_not_silently_a_total_match_count(repository):
    feed = {"jobs": [post(index) for index in range(10, 15)]}
    service = GreenhouseService(client=client_for(lambda request: httpx.Response(200, json=feed)), repository=repository)
    result = service.search(GreenhouseSearchRequest(board_token="example", query="Python", limit=2))
    assert len(result.candidates) == 2
    assert result.matched_count == 5


def test_import_is_atomic_and_reuses_existing_identity(repository, job_sessions):
    data = normalize_post(post()).data
    first, created = repository.import_once("example", 101, data)
    second, created_again = repository.import_once("example", 101, data)
    assert created and not created_again
    assert first == second
    with job_sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalJobIdentity)) == 1


def test_identity_includes_board(repository):
    data = normalize_post(post()).data
    first, _ = repository.import_once("one", 101, data)
    other, _ = repository.import_once("two", 101, data)
    assert first.id != other.id


def test_identity_write_failure_rolls_back_the_new_job(repository, job_sessions, monkeypatch):
    original = Session.add

    def fail(session, instance, *args, **kwargs):
        if isinstance(instance, ExternalJobIdentity):
            raise IntegrityError("Injected failure", {}, RuntimeError("test"))
        return original(session, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "add", fail)
    with pytest.raises(IntegrityError):
        repository.import_once("example", 101, normalize_post(post()).data)
    with job_sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_concurrent_imports_keep_one_job(repository, job_sessions):
    data = normalize_post(post()).data
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: repository.import_once("example", 101, data), range(4)))
    assert len({job.id for job, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    with job_sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_reimport_never_overwrites_a_saved_job(repository):
    first, _ = repository.import_once("example", 101, normalize_post(post()).data)
    changed = normalize_post(post(title="Changed job title")).data
    second, created = repository.import_once("example", 101, changed)
    assert not created
    assert second == first


def test_identity_survives_a_fresh_database_engine(repository, job_sessions):
    from pathlib import Path
    from sqlalchemy.orm import sessionmaker
    from app.db.database import create_sqlite_engine

    saved, _ = repository.import_once("example", 101, normalize_post(post()).data)
    with job_sessions() as session:
        old = session.get_bind()
        path = Path(old.url.database)
    old.dispose()
    reopened = create_sqlite_engine(path)
    try:
        restored = ExternalJobRepository(sessionmaker(bind=reopened))
        assert restored.find("example", 101) == saved
        duplicate, created = restored.import_once("example", 101, normalize_post(post()).data)
        assert not created and duplicate == saved
    finally:
        reopened.dispose()


@pytest.mark.parametrize("payload", [{}, {"jobs": {}}, {"jobs": [None] * 10_001}])
def test_unsupported_feed_shape_or_size_is_rejected(repository, payload):
    service = GreenhouseService(
        client=client_for(lambda request: httpx.Response(200, json=payload)), repository=repository,
    )
    with pytest.raises(CollectionError) as exc:
        service.search(GreenhouseSearchRequest(board_token="example", query="Python"))
    assert exc.value.status_code == 502


def test_service_reimport_makes_no_provider_call(repository):
    repository.import_once("example", 101, normalize_post(post()).data)
    service = GreenhouseService(
        client=client_for(lambda request: pytest.fail("Existing import should not fetch")), repository=repository,
    )
    result = service.import_job(GreenhouseImportRequest(board_token="example", external_id=101))
    assert not result.created


def test_provider_id_mismatch_is_not_persisted(repository):
    service = GreenhouseService(
        client=client_for(lambda request: httpx.Response(200, json=post(999))), repository=repository,
    )
    with pytest.raises(CollectionError, match="different job"):
        service.import_job(GreenhouseImportRequest(board_token="example", external_id=101))
    assert repository.find("example", 101) is None


@pytest.fixture
def collection_api(repository, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [post()]})
        return httpx.Response(200, json=post(company_name="Example Company"))

    monkeypatch.setattr(greenhouse_service, "client", client_for(handler))
    monkeypatch.setattr(greenhouse_service, "repository", repository)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False), requests


def test_api_search_then_import_then_reimport(collection_api):
    client, requests = collection_api
    search = client.post("/jobs/search/greenhouse", json={"board_token": "example", "query": "Python"})
    assert search.status_code == 200
    post_id = search.json()["candidates"][0]["external_id"]
    body = {"board_token": "example", "external_id": post_id}
    first = client.post("/jobs/import/greenhouse", json=body)
    second = client.post("/jobs/import/greenhouse", json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert len(requests) == 2


@pytest.mark.parametrize("body", [
    {"board_token": "../private", "query": "Python"}, {"board_token": "example", "query": "  "},
    {"board_token": "example", "query": "Python", "limit": 51},
])
def test_invalid_search_never_fetches(collection_api, body):
    client, requests = collection_api
    assert client.post("/jobs/search/greenhouse", json=body).status_code == 422
    assert requests == []


def test_invalid_import_id_never_fetches(collection_api):
    client, requests = collection_api
    assert client.post("/jobs/import/greenhouse", json={"board_token": "example", "external_id": True}).status_code == 422
    assert requests == []


def test_api_preserves_rate_limit_headers(collection_api, monkeypatch):
    client, _ = collection_api
    monkeypatch.setattr(greenhouse_service, "client", client_for(
        lambda request: httpx.Response(429, headers={"Retry-After": "30"}),
    ))
    response = client.post("/jobs/search/greenhouse", json={"board_token": "example", "query": "Python"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"


def test_failed_provider_import_makes_no_identity(collection_api, repository, monkeypatch):
    client, _ = collection_api
    monkeypatch.setattr(greenhouse_service, "client", client_for(
        lambda request: httpx.Response(403),
    ))
    response = client.post("/jobs/import/greenhouse", json={"board_token": "example", "external_id": 101})
    assert response.status_code == 403
    assert repository.find("example", 101) is None