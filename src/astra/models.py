import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "missing_results",
    "broken_promises",
    "track_record",
    "pattern_finder",
    "side_effect",
    "timeline",
]
ConditionGroup = Literal["oncology", "cardiovascular", "cns_mental_health", "metabolic_t2d"]


class Intervention(BaseModel):
    type: str
    name: str


class RegisteredOutcome(BaseModel):
    measure: str
    time_frame: str | None = None


class ReportedOutcome(BaseModel):
    title: str
    time_frame: str | None = None


class SeriousTerm(BaseModel):
    term: str
    affected: int


class AdverseEvents(BaseModel):
    total_serious_affected: int
    total_at_risk: int
    total_deaths: int | None = None
    top_serious_terms: list[SeriousTerm] = []


class ParsedStudy(BaseModel):
    """One ClinicalTrials.gov study; field names match the `studies` table columns."""

    nct_id: str
    condition_group: str
    title: str
    brief_summary: str | None = None
    detailed_description: str | None = None
    conditions: list[str] = []
    interventions: list[Intervention] = []
    study_type: str | None = None
    phases: list[str] = []
    enrollment: int | None = None
    overall_status: str
    why_stopped: str | None = None
    sponsor: str
    sponsor_class: str | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    primary_completion_type: str | None = None
    completion_date: date | None = None
    completion_type: str | None = None
    first_posted: date | None = None
    last_update_posted: date | None = None
    results_first_posted: date | None = None
    has_results: bool = False
    is_fda_regulated: bool = False
    is_applicable_trial: bool = False
    registered_primary_outcomes: list[RegisteredOutcome] = []
    reported_primary_outcomes: list[ReportedOutcome] = []
    adverse_events: AdverseEvents | None = None
    reference_pmids: list[str] = []


class ParsedPaper(BaseModel):
    pmid: str
    title: str
    abstract: str | None = None
    journal: str | None = None
    pub_date: date | None = None
    linked_nct_ids: list[str] = []


# Field descriptions are part of the JSON schema the model sees in structured calls.
class EvidenceItem(BaseModel):
    source: Literal["registry", "paper", "aggregate"]
    reference: str = Field(
        description='Exactly one source ID: an NCT ID, "PMID <number>", "sponsor:<name>" or '
        '"group:<value>". No paths or field names.'
    )
    detail: str = Field(description="The specific fact, taken from a tool result")


class SignalDraft(BaseModel):
    nct_id: str | None = None
    sponsor: str | None = None
    related_nct_ids: list[str] = []
    title: str = Field(description="A short description of the finding, at most 120 characters")
    summary: str = Field(description="2-4 sentences, plain language")
    evidence: list[EvidenceItem]
    confidence: float = Field(description="0 to 1")


class AgentFindings(BaseModel):
    signals: list[SignalDraft]
    notes: str = Field(description='What was checked, including "nothing found"')


class AgentResult(BaseModel):
    agent: AgentName
    signals: list[SignalDraft] = []
    notes: str = ""
    steps: int = 0
    tool_calls: int = 0
    tools_used: list[str] = []
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    error: str | None = None


class ValidatedSignal(SignalDraft):
    agent: AgentName
    signal_type: str
    threshold: float
    citation_verified: bool | None = None


class SavedSignal(ValidatedSignal):
    signal_id: uuid.UUID
    status: Literal["auto_approved", "pending_review", "approved", "rejected"]


class RoutingDecision(BaseModel):
    in_scope: bool = Field(description="Is this a clinical-trial reporting question?")
    agents: list[AgentName] = []
    condition_group: ConditionGroup | None = None
    reason: str = Field(description="One or two sentences, shown in the UI")


class RuleChange(BaseModel):
    action: Literal["added", "none"]
    rule_id: uuid.UUID | None = None
    rule_text: str | None = None
