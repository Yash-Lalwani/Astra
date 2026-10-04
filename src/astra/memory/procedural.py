"""Procedural memory: how each agent should reason. The default rules are rewritten from the
reference project to use only data Astra actually has; learned rules come from rejections."""

from langmem import create_memory_manager
from pydantic import BaseModel

from astra import llm
from astra.models import RuleChange, SavedSignal
from astra.queries import rules as rule_queries

RULE_INSTRUCTIONS = (
    "A human reviewer rejected a finding made by a clinical-trial auditing agent. Write ONE "
    "short, general, reusable rule (one sentence) that would have prevented this mistake. Do not "
    "name specific NCT IDs or sponsors. If an existing rule already covers the reviewer's point, "
    "return no new rule."
)


class AgentRule(BaseModel):
    content: str


DEFAULT_RULES: dict[str, list[str]] = {
    "missing_results": [
        "Flag a trial only when a tool reports results_due: true for it; never work out the "
        "deadline yourself.",
        "Terminated and still-active trials are not covered by the results-due rule here; do not "
        "flag them as missing results.",
        "If enrollment is 0 or under 10 participants, mention it and keep confidence at or "
        "below 0.5: a trial that barely started may have nothing to report.",
        "Check the sponsor's profile before setting confidence: a single miss by a sponsor with a "
        "high compliance_rate deserves less confidence than one by a sponsor with a low rate. A "
        "null compliance_rate means too little data and changes nothing.",
        "The longer a trial is overdue, the higher the confidence; under 6 months overdue, stay "
        "below 0.7.",
    ],
    "broken_promises": [
        "ClinicalTrials.gov fills the results section from the registered outcomes, so "
        "compare_outcomes almost never shows a switch. Compare the registered primary outcome "
        "with the primary outcome named in the abstracts of linked papers instead.",
        "Flag only when a linked paper reports a different PRIMARY outcome from the registered "
        "one. Differences in secondary outcomes alone are not outcome switching.",
        "The same outcome measured with a different method or time frame is weaker evidence "
        "than a different outcome; keep such signals at or below 0.6 confidence.",
        "Do not flag when the abstract does not clearly name its primary outcome, or when the "
        "paper is a protocol, design paper or secondary analysis.",
    ],
    "track_record": [
        "Use the sponsor's compliance_rate as its credibility. Below 0.6 is a low_credibility "
        "signal; between 0.6 and 0.75 is concerning, so mention it in the notes without a signal.",
        "If compliance_rate is null (fewer than 3 applicable completed trials), do not flag the "
        "sponsor: there is not enough data.",
        "Weigh the size of the evidence, not only the rate: 1 missing of 3 is weaker than 5 "
        "missing of 15. Long-overdue trials weigh more than ones only a few months late.",
        "Astra only knows the lead sponsor of each trial; judge a sponsor only on trials it leads.",
    ],
    "pattern_finder": [
        "A pattern needs at least 3 trials in a group; ignore smaller groups.",
        "Flag a group only when its deviation_from_mean is 0.25 or more, and give the group's "
        "value, its size and the overall average in the evidence.",
        "Patterns within one sponsor are more actionable than patterns across different sponsors.",
        "Astra has no drug or mechanism-of-action data; compare only the computed rates and do "
        "not speculate about drugs.",
    ],
    "side_effect": [
        "Only papers published after the trial's primary completion date can be judged on safety "
        "reporting; earlier papers report interim data.",
        "The strongest signal: the registry posts serious adverse events or deaths, but a linked "
        "paper's abstract says there were none or calls the treatment well tolerated without "
        "mentioning them.",
        "Different wording for the same event is minor and deserves low confidence; a difference "
        "in severity (serious in the registry, mild in the paper) deserves high confidence.",
        "Abstracts are short and often leave out safety details. A missing mention alone is weak "
        "evidence (at most 0.6) unless the abstract makes an explicit safety claim.",
    ],
    "timeline": [
        "Flag a trial only when a tool reports silent_delay or unknown_status for it.",
        "COVID-19 is a legitimate reason for delays between March 2020 and December 2022: when the "
        "estimated date falls in that window, lower the confidence.",
        "A trial still recruiting past its estimated date may simply have underestimated "
        "enrollment time; that alone is not suspicious unless the record is also long out of date.",
        "UNKNOWN status means the record has not been verified for 2+ years; the longer since the "
        "last update, the higher the confidence.",
        "Completed trials past their results deadline belong to Missing Results; do not flag them "
        "here.",
    ],
}


async def seed_default_rules() -> None:
    await rule_queries.seed_rules(
        [(agent, rule) for agent, rules in DEFAULT_RULES.items() for rule in rules]
    )


async def get_rules(agent: str) -> list[dict]:
    """All of the agent's rules, default and learned, oldest first."""
    return await rule_queries.rules_for(agent)


def rejection_message(signal: SavedSignal, reviewer_reason: str) -> str:
    evidence = "\n".join(f"- {item.reference}: {item.detail}" for item in signal.evidence)
    return (
        f"Agent: {signal.agent} (signal type {signal.signal_type})\n"
        f"Rejected finding: {signal.title} (confidence {signal.confidence:.2f})\n"
        f"Summary: {signal.summary}\n"
        f"Evidence:\n{evidence}\n"
        f"Reviewer's reason for rejecting it: {reviewer_reason}"
    )


async def learn_from_rejection(signal: SavedSignal, reviewer_reason: str) -> RuleChange:
    """Turn a reviewer's rejection into one general rule for the agent, linked to the signal."""
    existing = [(str(rule["rule_id"]), AgentRule(content=rule["rule_text"]))
                for rule in await get_rules(signal.agent)]  # fmt: skip
    manager = create_memory_manager(
        llm.plain_model("fast"),
        schemas=[AgentRule],
        instructions=RULE_INSTRUCTIONS,
        enable_inserts=True,
        enable_updates=False,
        enable_deletes=False,
    )
    memories = await manager.ainvoke(
        {
            "messages": [{"role": "user", "content": rejection_message(signal, reviewer_reason)}],
            "existing": existing,
        }
    )
    existing_ids = {memory_id for memory_id, _ in existing}
    new_rules = [memory.content.content for memory in memories if memory.id not in existing_ids]
    if not new_rules:
        return RuleChange(action="none")
    # The instructions ask for one rule; if the model writes more, only the first is kept.
    row = await rule_queries.insert_learned_rule(
        signal.agent, new_rules[0], signal.signal_id, reviewer_reason
    )
    if row is None:
        return RuleChange(action="none")
    return RuleChange(action="added", rule_id=row["rule_id"], rule_text=row["rule_text"])
