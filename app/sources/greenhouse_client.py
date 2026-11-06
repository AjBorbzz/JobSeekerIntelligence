import copy
import json
import math
import re
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from threading import Lock

import httpx

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/"
BOARD_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")


class CollectionError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def retry_delay(value: str | None) -> int:
    if value and len(value) <= 128:
        if value.isdigit():
            return max(1, int(value))
        try:
            return max(1, math.ceil(parsedate_to_datetime(value).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            pass
    return 60


def reject_nonfinite(value: str):
    raise ValueError("Non-finite JSON value")


class GreenhouseClient:
    def __init__(self, transport=None, clock=time.monotonic, cache_ttl: float = 300,
                 min_interval: float = 2, max_bytes: int = 2_000_000):
        self.transport = transport
        self.clock = clock
        self.cache_ttl = cache_ttl
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self._cache = OrderedDict()
        self._next_attempt = 0.0
        self._blocked_until = 0.0
        self._lock = Lock()

    def fetch(self, board_token: str, external_id: int | None = None) -> tuple[dict, bool]:
        if BOARD_PATTERN.fullmatch(board_token) is None:
            raise CollectionError(422, "Invalid board token")
        if external_id is not None and (type(external_id) is not int or external_id < 1):
            raise CollectionError(422, "Invalid external post ID")
        path = board_token + "/jobs" + (f"/{external_id}" if external_id is not None else "")
        params = {"content": "true"} if external_id is None else None

        with self._lock:
            now = self.clock()
            cached = self._cache.get(path)
            if cached is not None and now - cached[0] < self.cache_ttl:
                self._cache.move_to_end(path)
                return copy.deepcopy(cached[1]), True
            wait = max(self._next_attempt, self._blocked_until) - now
            if wait > 0:
                raise CollectionError(429, "Collection cooldown is active", math.ceil(wait))
            self._next_attempt = now + self.min_interval

            try:
                with httpx.Client(
                    transport=self.transport, timeout=10.0, follow_redirects=False, trust_env=False,
                    headers={"User-Agent": "JobIntelligence/0.10 (local project)"},
                ) as client:
                    with client.stream("GET", BASE_URL + path, params=params) as response:
                        if response.status_code == 429:
                            delay = retry_delay(response.headers.get("Retry-After"))
                            self._blocked_until = self.clock() + delay
                            raise CollectionError(429, "Provider rate limit reached", delay)
                        if response.status_code in (401, 403):
                            raise CollectionError(403, "Provider denied access; do not bypass this restriction")
                        if response.status_code == 404:
                            raise CollectionError(404, "Board or job post was not found by the provider")
                        if response.status_code != 200:
                            raise CollectionError(502, "Provider returned an unsuccessful response")
                        data = bytearray()
                        for chunk in response.iter_bytes(chunk_size=16_384):
                            if self.clock() - now > 20:
                                raise CollectionError(504, "Provider response exceeded the elapsed-time budget")
                            data.extend(chunk)
                            if len(data) > self.max_bytes:
                                raise CollectionError(502, "Provider response exceeded the configured size limit")
                payload = json.loads(data, parse_constant=reject_nonfinite)
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
            except httpx.TimeoutException as exc:
                raise CollectionError(504, "Provider request timed out") from exc
            except httpx.HTTPError as exc:
                raise CollectionError(502, "Provider connection failed") from exc
            except (ValueError, RecursionError) as exc:
                raise CollectionError(502, "Provider returned unreadable JSON") from exc

            self._cache[path] = (self.clock(), copy.deepcopy(payload))
            self._cache.move_to_end(path)
            while len(self._cache) > 8:
                self._cache.popitem(last=False)
            return payload, False