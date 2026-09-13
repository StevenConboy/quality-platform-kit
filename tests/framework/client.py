"""HTTP clients for tests.

BaseApiClient is generic: retries on transport errors, records every exchange so a
failing test can show exactly what was sent and received. TriageClient adds typed
helpers for the ticket-triage endpoints. Another service would subclass BaseApiClient
the same way.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# httpx2 rather than httpx: Starlette's TestClient and the Anthropic SDK are both built on it.
import httpx2

from app.models import HealthResponse, MetricsResponse, TriageRecord, TriageResponse
from tests.framework.structured_log import StructuredLogger

# 503 is deliberately absent: the app returns it on purpose for quota exhaustion and tests
# need to see it. 502/504 only ever come from something in front of the app.
DEFAULT_RETRY_STATUSES: tuple[int, ...] = (502, 504)


@dataclass
class Exchange:
    """One HTTP attempt, as sent and as received."""

    method: str
    url: str
    request_headers: dict[str, str]
    request_body: Any
    attempt: int
    status_code: int | None = None
    response_body: Any = None
    elapsed_ms: float = 0.0
    error: str | None = None

    def render(self) -> str:
        lines = [f"> {self.method} {self.url}  (attempt {self.attempt})"]
        for key, value in self.request_headers.items():
            lines.append(f"> {key}: {value}")
        if self.request_body is not None:
            lines.append("> " + json.dumps(self.request_body))
        if self.error:
            lines.append(f"< ERROR {self.error}")
        else:
            lines.append(f"< {self.status_code}  {self.elapsed_ms:.1f} ms")
            lines.append("< " + json.dumps(self.response_body, default=str))
        return "\n".join(lines)


@dataclass
class BaseApiClient:
    http: httpx2.Client
    max_retries: int = 2
    retry_statuses: tuple[int, ...] = DEFAULT_RETRY_STATUSES
    backoff_seconds: float = 0.1
    log: StructuredLogger | None = None
    exchanges: list[Exchange] = field(default_factory=list)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx2.Response:
        headers = headers or {}
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            exchange = Exchange(method, path, headers, json_body, attempt)
            started = time.perf_counter()
            try:
                response = self.http.request(
                    method, path, json=json_body, headers=headers, params=params
                )
            except httpx2.TransportError as exc:
                exchange.error = f"{type(exc).__name__}: {exc}"
                exchange.elapsed_ms = (time.perf_counter() - started) * 1000
                self.exchanges.append(exchange)
                last_error = exc
                self._sleep_before_retry(attempt)
                continue

            exchange.elapsed_ms = (time.perf_counter() - started) * 1000
            exchange.status_code = response.status_code
            exchange.response_body = _body_of(response)
            self.exchanges.append(exchange)
            if self.log:
                self.log.step(
                    "http", method=method, path=path, status=response.status_code, attempt=attempt
                )
            if response.status_code in self.retry_statuses and attempt <= self.max_retries:
                self._sleep_before_retry(attempt)
                continue
            return response

        raise RuntimeError(
            f"{method} {path} failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _sleep_before_retry(self, attempt: int) -> None:
        if attempt <= self.max_retries:
            time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

    def get(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("PUT", path, **kwargs)

    @property
    def last(self) -> Exchange:
        return self.exchanges[-1]

    def render_exchanges(self, limit: int = 10) -> str:
        return "\n\n".join(e.render() for e in self.exchanges[-limit:])


def _body_of(response: httpx2.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def fault_header(faults: Iterable[str] | None) -> dict[str, str]:
    """Build the X-Fault header for a set of fault names. Empty input means no header."""
    names = list(faults or [])
    return {"X-Fault": ",".join(names)} if names else {}


class TriageClient(BaseApiClient):
    """Typed helpers for ticket-triage. Each returns a parsed model or the raw response."""

    def triage_raw(
        self, ticket: dict[str, Any], *, faults: Iterable[str] | None = None
    ) -> httpx2.Response:
        return self.post("/triage", json_body=ticket, headers=fault_header(faults))

    def triage(
        self, ticket: dict[str, Any], *, faults: Iterable[str] | None = None
    ) -> TriageResponse:
        response = self.triage_raw(ticket, faults=faults)
        assert response.status_code == 200, f"expected 200, got {self.last.render()}"
        return TriageResponse.model_validate(response.json())

    def triage_healthy(self, ticket: dict[str, Any], *, attempts: int = 3) -> TriageResponse:
        """Triage that is expected to succeed. Retries only when the app reports the
        upstream provider was unavailable, which on a real network is a transient blip
        rather than a finding. Any other degradation is returned as is."""
        result = self.triage(ticket)
        for _ in range(attempts - 1):
            if result.degradation_reason != "llm_unavailable":
                break
            if self.log:
                self.log.warn("upstream unavailable, retrying baseline", asset=ticket["asset_id"])
            time.sleep(1.0)
            result = self.triage(ticket)
        return result

    def health(self, *, probe: bool = False, faults: Iterable[str] | None = None) -> HealthResponse:
        response = self.get(
            "/health", params={"probe": str(probe).lower()}, headers=fault_header(faults)
        )
        assert response.status_code == 200, self.last.render()
        return HealthResponse.model_validate(response.json())

    def metrics(self) -> MetricsResponse:
        response = self.get("/metrics")
        assert response.status_code == 200, self.last.render()
        return MetricsResponse.model_validate(response.json())

    def recent(self, limit: int = 20) -> list[TriageRecord]:
        response = self.get("/triage/recent", params={"limit": limit})
        assert response.status_code == 200, self.last.render()
        return [TriageRecord.model_validate(item) for item in response.json()]

    def get_faults(self) -> dict[str, bool]:
        response = self.get("/faults")
        assert response.status_code == 200, self.last.render()
        enabled: dict[str, bool] = response.json()["enabled"]
        return enabled

    def set_faults(self, **flags: bool) -> dict[str, bool]:
        response = self.put("/faults", json_body=flags)
        assert response.status_code == 200, self.last.render()
        result: dict[str, bool] = response.json()
        return result
