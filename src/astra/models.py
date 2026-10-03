from datetime import date

from pydantic import BaseModel


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
