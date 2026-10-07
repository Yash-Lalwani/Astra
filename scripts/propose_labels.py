"""Propose about 25 golden trials for the trials eval, each label with the facts behind it.

Writes evals/data/proposed_trials.jsonl. Yash reviews and corrects it and saves the result as
evals/data/trials.jsonl; this script never writes that file.

missing_results and timeline_delay come from rules.py facts. broken_promise and safety_gap are
only hints from abstract text; they need a human reading the papers.

Usage: uv run python scripts/propose_labels.py
"""

import asyncio
import json
import re
from collections import Counter
from datetime import date
from itertools import zip_longest
from pathlib import Path

from astra.db import close_pool
from astra.ingestion.rules import results_due_status, timeline_status
from astra.models import ParsedStudy
from astra.queries.papers import linked_papers
from astra.queries.trials import all_studies

OUTPUT = Path("evals/data/proposed_trials.jsonl")
LABELS = ("missing_results", "broken_promise", "timeline_delay", "safety_gap")
POSITIVES_PER_LABEL = 5
TOTAL = 25
SAFETY_WORDS = re.compile(
    r"adverse|safety|\bsafe\b|tolera|toxic|serious|death|died|side effect", re.IGNORECASE
)
PRIMARY_SENTENCE = re.compile(r"primary (end ?point|outcome|efficacy)", re.I)
STOPWORDS = {"the", "of", "in", "to", "and", "a", "at", "with", "from", "for", "on", "by", "or",
             "as", "an", "number", "participants", "change", "baseline", "percentage"}  # fmt: skip
OUTCOME_OVERLAP_HINT = 0.3


def words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOPWORDS}


def outcome_overlap(measure: str, sentence: str) -> float:
    """Share of the registered outcome's words that appear in the paper's sentence."""
    measure_words = words(measure)
    return len(measure_words & words(sentence)) / len(measure_words) if measure_words else 0.0


def paper_facts(study: ParsedStudy, papers: list[dict]) -> list[dict]:
    facts = []
    for paper in papers:
        abstract = paper["abstract"] or ""
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", abstract) if PRIMARY_SENTENCE.search(s)]
        overlaps = [
            outcome_overlap(outcome.measure, sentence)
            for outcome in study.registered_primary_outcomes
            for sentence in sentences
        ]
        facts.append(
            {
                "pmid": paper["pmid"],
                "pub_date": str(paper["pub_date"]),
                "after_completion": bool(
                    paper["pub_date"]
                    and study.primary_completion_date
                    and paper["pub_date"] > study.primary_completion_date
                ),
                "mentions_safety": bool(SAFETY_WORDS.search(abstract)),
                "primary_sentence": sentences[0][:300] if sentences else None,
                "best_outcome_overlap": round(max(overlaps), 2) if overlaps else None,
            }
        )
    return facts


def propose(study: ParsedStudy, papers: list[dict], today: date) -> dict:
    due = results_due_status(study, today)
    timeline = timeline_status(study, today)
    facts = paper_facts(study, papers)
    serious = study.adverse_events.total_serious_affected if study.adverse_events else 0
    later_papers = [paper for paper in facts if paper["after_completion"]]
    compared = [paper for paper in facts if paper["best_outcome_overlap"] is not None]
    return {
        "nct_id": study.nct_id,
        "condition_group": study.condition_group,
        "title": study.title,
        "labels": {
            "missing_results": due["results_due"],
            "broken_promise": bool(compared)
            and min(paper["best_outcome_overlap"] for paper in compared) < OUTCOME_OVERLAP_HINT,
            "timeline_delay": timeline["silent_delay"] or timeline["unknown_status"],
            "safety_gap": serious > 0
            and bool(later_papers)
            and not any(paper["mentions_safety"] for paper in later_papers),
        },
        "label_basis": {
            "missing_results": "fact (results_due_status)",
            "broken_promise": "hint (registered outcome vs the abstract's primary endpoint)",
            "timeline_delay": "fact (timeline_status)",
            "safety_gap": "hint (serious AEs in registry, no safety words in later abstracts)",
        },
        "facts": {
            "overall_status": study.overall_status,
            "primary_completion": study.primary_completion_date,
            "primary_completion_type": study.primary_completion_type,
            "has_results": study.has_results,
            "is_applicable_trial": study.is_applicable_trial,
            "results_due": due,
            "timeline": timeline,
            "registered_primary_outcomes": [o.measure for o in study.registered_primary_outcomes],
            "serious_adverse_events": {
                "participants_affected": serious,
                "at_risk": study.adverse_events.total_at_risk if study.adverse_events else 0,
                "deaths": study.adverse_events.total_deaths if study.adverse_events else None,
            },
            "papers": facts,
        },
        "notes": "",
    }


def round_robin(proposals: list[dict]) -> list[dict]:
    """Interleave the condition groups so positives are spread across all four."""
    groups: dict[str, list[dict]] = {}
    for proposal in proposals:
        groups.setdefault(proposal["condition_group"], []).append(proposal)
    interleaved = zip_longest(*(groups[name] for name in sorted(groups)))
    return [proposal for row in interleaved for proposal in row if proposal is not None]


def select(proposals: list[dict]) -> list[dict]:
    """Up to 5 likely positives per label, spread over the condition groups, then fill to 25
    with trials that are negative for every label."""
    chosen: dict[str, dict] = {}
    for label in LABELS:
        have = sum(proposal["labels"][label] for proposal in chosen.values())
        candidates = [p for p in proposals if p["labels"][label] and p["nct_id"] not in chosen]
        for proposal in round_robin(candidates)[: max(POSITIVES_PER_LABEL - have, 0)]:
            chosen[proposal["nct_id"]] = proposal
    clean = [p for p in proposals if not any(p["labels"].values()) and p["nct_id"] not in chosen]
    for proposal in round_robin(clean)[: max(TOTAL - len(chosen), 0)]:
        chosen[proposal["nct_id"]] = proposal
    return sorted(chosen.values(), key=lambda p: (p["condition_group"], p["nct_id"]))


async def main() -> None:
    today = date.today()
    proposals = []
    for study in await all_studies():
        papers = await linked_papers(study.nct_id, limit=50)
        if any(paper["is_synthetic"] for paper in papers):
            continue  # guardrail demo trials are never eval data
        proposals.append(propose(study, papers, today))
    await close_pool()

    selected = select(proposals)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(p, default=str) + "\n" for p in selected))

    pool = Counter(label for p in proposals for label in LABELS if p["labels"][label])
    print(f"Candidates: {len(proposals)} trials; likely positives in the whole pool: {dict(pool)}")
    print(f"Wrote {len(selected)} proposals to {OUTPUT}")
    for label in LABELS:
        positives = sum(p["labels"][label] for p in selected)
        print(f"  {label:16} {positives} positive, {len(selected) - positives} negative")


if __name__ == "__main__":
    asyncio.run(main())
