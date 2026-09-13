"""Request and response schemas for the ticket-triage API."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Priority = Literal["critical", "high", "medium", "low"]
Category = Literal["electrical", "plumbing", "hvac", "structural", "safety", "it", "general"]
ResultSource = Literal["llm", "fallback"]

PRIORITIES: tuple[str, ...] = get_args(Priority)
CATEGORIES: tuple[str, ...] = get_args(Category)


class Ticket(BaseModel):
    """A maintenance ticket as submitted by a client."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200, examples=["Breaker tripping in server room"])
    description: str = Field(
        min_length=1,
        max_length=4000,
        examples=["Main breaker for rack B trips every few hours. Smell of burning plastic."],
    )
    asset_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")

    @field_validator("title", "description")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @property
    def text(self) -> str:
        """Title and description together, for keyword scans."""
        return f"{self.title}\n{self.description}"


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class TriageResponse(BaseModel):
    ticket_id: str
    priority: Priority
    category: Category
    summary: str
    source: ResultSource
    degraded: bool = False
    degradation_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    faults_applied: list[str] = Field(
        default_factory=list, description="Faults injected into this request, from file or header"
    )
    model: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float


class ErrorResponse(BaseModel):
    error: str
    detail: str


class TriageRecord(BaseModel):
    """One entry in the recent-history list: what came in, what was injected, what went out."""

    received_at: str
    status_code: int
    faults_applied: list[str]
    ticket: Ticket
    response: TriageResponse | None = None
    error: ErrorResponse | None = None


class LLMStatus(BaseModel):
    status: Literal["ok", "degraded", "unreachable", "quota_exceeded", "unknown"]
    provider: str
    model: str
    last_error: str | None = None
    last_success_at: str | None = None
    consecutive_failures: int = 0
    probe_latency_ms: float | None = None


class BudgetStatus(BaseModel):
    limit: int
    spent: int
    remaining: int
    exhausted: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    llm: LLMStatus
    token_budget: BudgetStatus
    faults_active: list[str]


class LatencyStats(BaseModel):
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class LLMCallStats(BaseModel):
    total: int
    succeeded: int
    failed: int
    fallbacks: int


class MetricsResponse(BaseModel):
    requests_total: int
    requests_by_endpoint: dict[str, int]
    requests_by_status: dict[str, int]
    latency: LatencyStats
    latency_by_endpoint: dict[str, LatencyStats]
    llm_calls: LLMCallStats
    faults_injected: dict[str, int]
    tokens: BudgetStatus
    tokens_by_direction: TokenUsage
