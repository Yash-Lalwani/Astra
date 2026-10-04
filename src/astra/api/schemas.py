"""Every request and response model of the API. The frontend generates its TypeScript types from
/openapi.json, so these models are the contract."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from astra.models import (
    AdverseEvents,
    AgentName,
    ConditionGroup,
    EvidenceItem,
    ParsedStudy,
    RuleChange,
)


class Page[T](BaseModel):
    items: list[T]
    total: int


def to_page[T: BaseModel](rows: list[dict], model: type[T]) -> Page[T]:
    """Rows from a list query, each carrying the total match count as `total`."""
    return Page[model](
        items=[model.model_validate(row) for row in rows], total=rows[0]["total"] if rows else 0
    )


# --- system --------------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["ok", "error"]
    database: Literal["ok", "error"]
    layer: Literal["ok", "error", "disabled"]


class Stats(BaseModel):
    trials: int
    papers: int
    sponsors: int
    signals_total: int
    signals_pending_review: int
    human_approval_rate: float | None
    runs_completed: int
    last_ingested_at: datetime | None


class AgentInfo(BaseModel):
    name: AgentName
    display_name: str
    description: str
    signal_type: str
    level: Literal["trial", "sponsor", "aggregate"]
    threshold: float
    tools: list[str]
    rule_count: int


class GraphDiagram(BaseModel):
    mermaid: str


# --- runs ----------------------------------------------------------------------------


class RunCreate(BaseModel):
    task: str = Field(min_length=3, max_length=500)
    condition_group: ConditionGroup | None = None


class RunCreated(BaseModel):
    run_id: uuid.UUID
    status: str


class RunCapReached(BaseModel):
    message: str
    limit: int


class AgentStats(BaseModel):
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    duration_ms: int
    signals: int
    error: str | None


class RunSummary(BaseModel):
    run_id: uuid.UUID
    task: str
    status: str
    created_by: str
    is_showcase: bool
    selected_agents: list[str]
    condition_group: str | None
    signals_count: int
    pending_review_count: int
    input_tokens: int
    output_tokens: int
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None


class Signal(BaseModel):
    signal_id: uuid.UUID
    run_id: uuid.UUID
    agent: str
    signal_type: str
    nct_id: str | None
    sponsor: str | None
    related_nct_ids: list[str]
    title: str
    summary: str
    evidence: list[EvidenceItem]
    confidence: float
    threshold: float
    citation_verified: bool | None
    status: str
    edited: bool
    original_summary: str | None
    review_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime


class RunDetail(RunSummary):
    routing_reason: str | None
    brief: str | None
    agent_stats: dict[str, AgentStats]
    error: str | None
    started_at: datetime | None
    signals: list[Signal]


# --- trials and sponsors -------------------------------------------------------------


class ResultsDue(BaseModel):
    results_due: bool
    months_overdue: int


class TimelineStatus(BaseModel):
    silent_delay: bool
    days_past_estimated: int
    months_since_update: int
    unknown_status: bool


class OutcomePair(BaseModel):
    registered: str
    best_reported: str
    similarity: float
    time_frame_similarity: float
    possible_switch: bool


class OutcomeComparison(BaseModel):
    comparable: bool
    registered_count: int
    reported_count: int
    count_difference: int
    pairs: list[OutcomePair]
    unmatched_registered: list[str]
    unmatched_reported: list[str]
    max_mismatch: float


class TrialFacts(BaseModel):
    is_applicable_trial: bool
    results_due: ResultsDue
    timeline: TimelineStatus
    outcome_comparison: OutcomeComparison
    adverse_events: AdverseEvents | None


class Paper(BaseModel):
    pmid: str
    title: str
    journal: str | None
    pub_date: date | None
    abstract: str | None
    is_synthetic: bool
    link_source: str


class TrialDetail(BaseModel):
    study: ParsedStudy
    facts: TrialFacts
    papers: list[Paper]
    signals: list[Signal]


class TrialRow(BaseModel):
    nct_id: str
    title: str
    sponsor: str
    condition_group: str
    overall_status: str
    phases: list[str]
    start_date: date | None
    primary_completion_date: date | None
    primary_completion_type: str | None
    has_results: bool
    is_applicable_trial: bool


class Sponsor(BaseModel):
    sponsor: str
    sponsor_class: str | None
    total_studies: int
    applicable_completed: int
    results_posted: int
    missing_results: int
    compliance_rate: float | None
    avg_reporting_delay_days: float | None
    updated_at: datetime


class SponsorDetail(BaseModel):
    profile: Sponsor
    trials: list[TrialRow]
    signals: list[Signal]


# --- review and memory ---------------------------------------------------------------


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    reason: str | None = None
    edited_summary: str | None = None

    @model_validator(mode="after")
    def required_fields(self) -> "ReviewDecision":
        if self.decision == "reject" and len((self.reason or "").strip()) < 10:
            raise ValueError("a rejection needs a reason of at least 10 characters")
        if self.decision == "edit" and not (self.edited_summary or "").strip():
            raise ValueError("an edit needs edited_summary")
        return self


class ReviewResult(BaseModel):
    signal: Signal
    rule_change: RuleChange | None


class Rule(BaseModel):
    rule_id: uuid.UUID
    agent: str
    rule_text: str
    source: Literal["default", "learned"]
    learned_from_signal_id: uuid.UUID | None
    reviewer_reason: str | None
    created_at: datetime


class EpisodeSignal(BaseModel):
    signal_id: uuid.UUID
    nct_id: str | None
    sponsor: str | None
    title: str
    confidence: float


class Episode(BaseModel):
    run_id: uuid.UUID
    agent: str
    task: str
    created_at: datetime
    summary: str
    signals: list[EpisodeSignal]
    score: float | None


# --- trust ---------------------------------------------------------------------------


class EvalRun(BaseModel):
    eval_id: uuid.UUID
    suite: str
    models: dict[str, Any]
    dataset_size: int
    metrics: dict[str, Any]
    created_at: datetime


class ApprovalPoint(BaseModel):
    agent: str | None  # None in the overall series
    week: date
    approved: int
    rejected: int
    approval_rate: float


class ApprovalRate(BaseModel):
    by_agent: list[ApprovalPoint]
    overall: list[ApprovalPoint]


class GuardrailEvent(BaseModel):
    event_id: int
    run_id: uuid.UUID | None
    stage: str
    agent: str | None
    action: str
    reason: str
    detail: dict[str, Any]
    created_at: datetime


class GuardrailEventPage(Page[GuardrailEvent]):
    counts: dict[str, int]
