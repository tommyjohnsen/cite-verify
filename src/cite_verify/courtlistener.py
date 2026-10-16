from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .cache import LocalCache
from .extract import ExtractedCitation, normalize_citation

ENDPOINT = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
MAX_CITATIONS = 250
MAX_CHARACTERS = 64_000
DAILY_BUDGET = 125


@dataclass(frozen=True, slots=True)
class Lookup:
    status: int
    authoritative: str = ""
    source_url: str = ""
    matched_field: str = ""
    reason: str = ""

    def cache_value(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "authoritative": self.authoritative,
            "source_url": self.source_url,
            "matched_field": self.matched_field,
            "reason": self.reason,
        }


class BudgetExhausted(RuntimeError):
    pass


Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, str], bytes]]


def _transport(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def make_batches(citations: Iterable[ExtractedCitation]) -> list[list[ExtractedCitation]]:
    batches: list[list[ExtractedCitation]] = []
    current: list[ExtractedCitation] = []
    size = 0
    for citation in citations:
        addition = len(citation.text) + (1 if current else 0)
        if current and (len(current) >= MAX_CITATIONS or size + addition > MAX_CHARACTERS):
            batches.append(current)
            current, size = [], 0
            addition = len(citation.text)
        if len(citation.text) > MAX_CHARACTERS:
            raise ValueError("a citation exceeds the request character limit")
        current.append(citation)
        size += addition
    if current:
        batches.append(current)
    return batches


class CourtListenerClient:
    def __init__(
        self,
        token: str,
        cache: LocalCache,
        *,
        transport: Transport = _transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        daily_budget: int = DAILY_BUDGET,
    ) -> None:
        self._token = token
        self.cache = cache
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.daily_budget = daily_budget
        self.requests_used = 0
        self._last_request: float | None = None

    def lookup(self, citations: list[ExtractedCitation]) -> dict[str, Lookup]:
        output: dict[str, Lookup] = {}
        missing: list[ExtractedCitation] = []
        for citation in citations:
            cached = self.cache.get("courtlistener", citation.normalized)
            if cached is None:
                missing.append(citation)
            else:
                output[citation.normalized] = Lookup(**cached)
        for batch in make_batches(missing):
            if self.requests_used >= self.daily_budget:
                for citation in batch:
                    output[citation.normalized] = Lookup(0, reason="daily budget exhausted")
                continue
            response = self._request(batch)
            for citation, lookup in zip(batch, response, strict=True):
                output[citation.normalized] = lookup
                self.cache.put("courtlistener", citation.normalized, lookup.cache_value())
        return output

    def _wait(self) -> None:
        if self._last_request is not None:
            remaining = 12.0 - (self.clock() - self._last_request)
            if remaining > 0:
                self.sleep(remaining)

    def _request(self, batch: list[ExtractedCitation]) -> list[Lookup]:
        payload = json.dumps({"text": "\n".join(c.text for c in batch)}).encode()
        headers = {
            "Authorization": f"Token {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        while True:
            if self.requests_used >= self.daily_budget:
                return [Lookup(0, reason="daily budget exhausted") for _ in batch]
            self._wait()
            status, response_headers, body = self.transport(ENDPOINT, headers, payload)
            self._last_request = self.clock()
            self.requests_used += 1
            if status != 429:
                break
            retry = response_headers.get("Retry-After", response_headers.get("retry-after", "12"))
            try:
                delay = max(0.0, float(retry))
            except ValueError:
                delay = 12.0
            self.sleep(delay)
        if status != 200:
            reason = {300: "ambiguous", 400: "bad request", 404: "not found"}.get(status, f"HTTP {status}")
            return [Lookup(status, reason=reason) for _ in batch]
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return [Lookup(0, reason="invalid response") for _ in batch]
        return self._decode(data, batch)

    @staticmethod
    def _decode(data: Any, batch: list[ExtractedCitation]) -> list[Lookup]:
        items = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return [Lookup(0, reason="invalid response") for _ in batch]
        decoded: list[Lookup] = []
        for index, citation in enumerate(batch):
            item = items[index] if index < len(items) and isinstance(items[index], dict) else {}
            status = int(item.get("status", 200 if item else 404))
            normalized = item.get("normalized_citations")
            if isinstance(normalized, list):
                normalized = normalized[0] if normalized else ""
            authoritative = str(normalized or item.get("normalized_citation") or item.get("citation") or "")
            clusters = item.get("clusters")
            cluster = clusters[0] if isinstance(clusters, list) and clusters and isinstance(clusters[0], dict) else {}
            url = str(item.get("absolute_url") or item.get("url") or cluster.get("absolute_url") or cluster.get("url") or "")
            if url.startswith("/"):
                url = "https://www.courtlistener.com" + url
            matched = str(item.get("matched_field") or ("reporter+volume+page" if authoritative else ""))
            reason = str(item.get("reason") or ("authoritative match" if authoritative else "not found"))
            decoded.append(Lookup(status, authoritative, url, matched, reason))
        return decoded
