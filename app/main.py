"""FastAPI application factory and routes for ticket-triage."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.budget import TokenBudget
from app.config import Settings
from app.faults import FAULT_DESCRIPTIONS, FaultConfig, UnknownFault, resolve_faults
from app.health import ProviderStatus
from app.logging_setup import configure_logging
from app.metrics import Metrics
from app.models import (
    ErrorResponse,
    HealthResponse,
    LLMStatus,
    MetricsResponse,
    Ticket,
    TriageResponse,
)
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider, ProviderError, ProviderTimeout
from app.providers.fake import FakeProvider
from app.triage import QuotaExhausted, TriageService

log = logging.getLogger("api")

QUOTA_RETRY_AFTER_SECONDS = 60


@dataclass
class AppState:
    settings: Settings
    faults: FaultConfig
    budget: TokenBudget
    metrics: Metrics
    status: ProviderStatus
    provider: LLMProvider
    service: TriageService


def build_provider(settings: Settings) -> LLMProvider:
    if settings.provider == "anthropic":
        return AnthropicProvider(
            model=settings.model,
            timeout_seconds=settings.llm_timeout_seconds,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
    return FakeProvider()


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    """Build an app instance. Tests call this directly to get isolated state."""
    configure_logging()
    settings = settings or Settings.from_env()
    provider = provider or build_provider(settings)
    budget = TokenBudget(settings.token_budget)
    metrics = Metrics()
    status = ProviderStatus()
    state = AppState(
        settings=settings,
        faults=FaultConfig(settings.faults_file),
        budget=budget,
        metrics=metrics,
        status=status,
        provider=provider,
        service=TriageService(provider, settings, budget, metrics, status),
    )

    app = FastAPI(
        title="ticket-triage",
        version="0.1.0",
        description=(
            "Triage maintenance tickets with an LLM. Includes a fault injection layer "
            "for resilience testing; see app/README.md."
        ),
    )
    app.state.kit = state

    @app.middleware("http")
    async def record_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - started) * 1000
        metrics.record_request(request.url.path, response.status_code, latency_ms)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round(latency_ms, 2),
                "x_fault": request.headers.get("x-fault"),
            },
        )
        return response

    @app.exception_handler(QuotaExhausted)
    async def quota_exhausted_handler(request: Request, exc: QuotaExhausted) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": str(QUOTA_RETRY_AFTER_SECONDS)},
            content=ErrorResponse(
                error="token_budget_exhausted",
                detail="LLM token budget is spent. Triage is paused until it is raised or reset.",
            ).model_dump(),
        )

    app.include_router(_build_routes())
    return app


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.kit
    return state


def get_active_faults(
    state: Annotated[AppState, Depends(get_state)],
    x_fault: Annotated[str | None, Header()] = None,
) -> frozenset[str]:
    try:
        return resolve_faults(state.faults.enabled, x_fault)
    except UnknownFault as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


State = Annotated[AppState, Depends(get_state)]
ActiveFaults = Annotated[frozenset[str], Depends(get_active_faults)]


def _build_routes() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/triage",
        response_model=TriageResponse,
        responses={503: {"model": ErrorResponse}, 400: {"description": "Unknown fault name"}},
        summary="Triage a maintenance ticket",
    )
    async def triage(ticket: Ticket, state: State, faults: ActiveFaults) -> TriageResponse:
        return await state.service.triage(ticket, faults)

    @router.get("/health", response_model=HealthResponse, summary="App and LLM status")
    async def health(
        state: State,
        faults: ActiveFaults,
        probe: Annotated[bool, Query(description="Actively ping the provider")] = False,
    ) -> HealthResponse:
        quota_exceeded = "quota_exceeded" in faults or state.budget.exhausted
        probe_latency_ms: float | None = None
        probe_error: str | None = None

        if probe:
            provider = state.service.provider_for(faults)
            started = time.perf_counter()
            try:
                await asyncio.wait_for(provider.ping(), timeout=state.settings.llm_timeout_seconds)
                state.status.record_success()
            except TimeoutError:
                probe_error = ProviderTimeout.reason
                state.status.record_failure(probe_error)
            except ProviderError as exc:
                probe_error = exc.reason
                state.status.record_failure(probe_error)
            probe_latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if quota_exceeded:
            llm_state = "quota_exceeded"
        elif probe_error is not None:
            llm_state = "unreachable"
        elif not state.status.healthy:
            llm_state = "degraded"
        elif state.status.last_success_at is None and not probe:
            llm_state = "unknown"
        else:
            llm_state = "ok"

        overall = "ok" if llm_state in ("ok", "unknown") else "degraded"
        return HealthResponse(
            status=overall,  # type: ignore[arg-type]
            llm=LLMStatus(
                status=llm_state,  # type: ignore[arg-type]
                provider=state.provider.name,
                model=state.provider.model,
                last_error=state.status.last_error,
                last_success_at=(
                    state.status.last_success_at.isoformat()
                    if state.status.last_success_at
                    else None
                ),
                consecutive_failures=state.status.consecutive_failures,
                probe_latency_ms=probe_latency_ms,
            ),
            token_budget=state.budget.status(force_exhausted=quota_exceeded),
            faults_active=sorted(faults),
        )

    @router.get("/metrics", response_model=MetricsResponse, summary="Request and token metrics")
    async def metrics(state: State) -> MetricsResponse:
        return state.metrics.snapshot(state.budget)

    @router.get("/faults", summary="Globally enabled faults and what each one does")
    async def list_faults(state: State) -> dict[str, object]:
        return {"enabled": state.faults.as_dict(), "descriptions": FAULT_DESCRIPTIONS}

    @router.put("/faults", summary="Enable or disable faults globally for this process")
    async def set_faults(flags: dict[str, bool], state: State) -> dict[str, bool]:
        try:
            for name, enabled in flags.items():
                state.faults.set(name, enabled)
        except UnknownFault as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.faults.as_dict()

    @router.post("/faults/reload", summary="Re-read faults.json")
    async def reload_faults(state: State) -> dict[str, bool]:
        try:
            state.faults.reload()
        except UnknownFault as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.faults.as_dict()

    return router


app = create_app()
