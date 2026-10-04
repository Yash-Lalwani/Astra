"""Signal validation (guardrail 3): every finding is checked against the data before it is saved.

Citation verification (guardrail 4) is added here when Layer-Engine is enabled; until then
citation_verified stays None.
"""

from astra.agents.registry import AGENTS, AgentConfig
from astra.models import AgentResult, SignalDraft, ValidatedSignal
from astra.queries import sponsors as sponsor_queries
from astra.queries import trials as trial_queries
from astra.queries.guardrails import log_event


def _normalise(draft: SignalDraft) -> SignalDraft:
    nct_id = (draft.nct_id or "").strip().upper() or None
    related = [nct.strip().upper() for nct in draft.related_nct_ids if nct.strip()]
    return draft.model_copy(update={"nct_id": nct_id, "related_nct_ids": related})


def _problem(
    config: AgentConfig, draft: SignalDraft, known_trials: set[str], sponsors: dict[str, str]
) -> str | None:
    """Why the signal must be dropped, or None when it passes."""
    if config.level == "trial" and not draft.nct_id:
        return "trial-level signal without an nct_id"
    if not (draft.nct_id or draft.sponsor):
        return "signal names neither a trial nor a sponsor"
    if draft.nct_id and draft.nct_id not in known_trials:
        return f"unknown nct_id {draft.nct_id}"
    if draft.sponsor and draft.sponsor.lower() not in sponsors:
        return f"unknown sponsor {draft.sponsor!r}"
    if not draft.evidence:
        return "no evidence"
    return None


async def validate_signals(
    agent_results: list[AgentResult], run_id: str | None
) -> tuple[list[ValidatedSignal], list[dict]]:
    """Returns the signals that pass and a {agent, reason} entry for each dropped one."""
    drafts = [
        (AGENTS[result.agent], _normalise(draft))
        for result in agent_results
        for draft in result.signals
    ]
    mentioned = {nct for _, draft in drafts for nct in [draft.nct_id, *draft.related_nct_ids]}
    known_trials = await trial_queries.existing_nct_ids(sorted(nct for nct in mentioned if nct))
    sponsors = await sponsor_queries.canonical_names(
        sorted({draft.sponsor for _, draft in drafts if draft.sponsor})
    )

    kept: dict[tuple[str, str], ValidatedSignal] = {}
    dropped: list[tuple[AgentConfig, SignalDraft, str]] = []
    for config, draft in drafts:
        problem = _problem(config, draft, known_trials, sponsors)
        if problem:
            dropped.append((config, draft, problem))
            continue
        signal = ValidatedSignal(
            **draft.model_dump(exclude={"sponsor", "related_nct_ids", "confidence"}),
            sponsor=sponsors[draft.sponsor.lower()] if draft.sponsor else None,
            related_nct_ids=[nct for nct in draft.related_nct_ids if nct in known_trials],
            confidence=min(max(draft.confidence, 0.0), 1.0),
            agent=config.name,
            signal_type=config.signal_type,
            threshold=config.threshold,
        )
        key = (config.name, signal.nct_id or signal.sponsor)
        if key in kept:
            weaker, signal = sorted([kept[key], signal], key=lambda item: item.confidence)
            dropped.append((config, weaker, "duplicate of a stronger signal"))
        kept[key] = signal

    for config, draft, problem in dropped:
        if run_id:
            await log_event(
                run_id,
                stage="signal_validation",
                action="dropped",
                reason=problem,
                agent=config.name,
                detail={"title": draft.title, "nct_id": draft.nct_id, "sponsor": draft.sponsor},
            )
    details = [{"agent": config.name, "reason": problem} for config, _, problem in dropped]
    return list(kept.values()), details
