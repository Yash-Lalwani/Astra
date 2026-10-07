"""Run the evals and store their aggregate metrics in eval_runs.

Usage: uv run python -m evals.run_eval --suite trials|routing|all

trials:  each trial-level agent assesses each golden trial (focused on it, no episodes); a
         prediction is positive when a validated signal of that agent for that trial has
         confidence >= 0.5. Scored as precision, recall and F1 per agent.
routing: route() alone, scored as exact-set accuracy and mean Jaccard.
Evals never write signals, runs or episodes (run_id is None and no store is used).
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from astra.agents.react_agent import run_specialist
from astra.agents.registry import AGENTS
from astra.agents.supervisor import route
from astra.config import configure_logging, settings
from astra.db import close_pool
from astra.guardrails.validator import validate_signals
from astra.queries.evals import insert_eval_run
from evals.metrics import confusion, jaccard, precision_recall_f1

DATA = Path(__file__).parent / "data"
POSITIVE_CONFIDENCE = 0.5
# Trial-level agent -> its label in trials.jsonl, and the task it is given for one trial.
TRIAL_AGENTS = {
    "missing_results": (
        "missing_results",
        "Assess {nct_id} for required results that were never posted",
    ),
    "broken_promises": (
        "broken_promise",
        "Assess {nct_id} for outcome switching between the registry and its papers",
    ),
    "timeline": ("timeline_delay", "Assess {nct_id} for being silently past its own schedule"),
    "side_effect": ("safety_gap", "Assess {nct_id} for serious adverse events its papers omit"),
}


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()]


def models_used() -> dict:
    return {
        "strong": settings.strong_model,
        "fast": settings.fast_model,
        "providers": settings.openrouter_provider_list,
        "layer_citation_checks": settings.layer_enabled,
    }


def fmt(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


async def predict_trial(nct_id: str) -> tuple[dict[str, bool], list[str]]:
    """Each trial-level agent's prediction for one trial, plus any agent errors."""
    results = await asyncio.gather(
        *(
            run_specialist(
                AGENTS[agent],
                task.format(nct_id=nct_id),
                run_id=None,
                focus_nct_ids=[nct_id],
                condition_group=None,
                use_episodes=False,
            )
            for agent, (_, task) in TRIAL_AGENTS.items()
        )
    )
    validated, _ = await validate_signals(list(results), run_id=None)
    predictions = {
        agent: any(
            signal.agent == agent
            and signal.nct_id == nct_id
            and signal.confidence >= POSITIVE_CONFIDENCE
            for signal in validated
        )
        for agent in TRIAL_AGENTS
    }
    errors = [f"{nct_id} {result.agent}: {result.error}" for result in results if result.error]
    return predictions, errors


async def run_trials() -> dict:
    golden = load("trials.jsonl")
    pairs: dict[str, list[tuple[bool, bool]]] = {agent: [] for agent in TRIAL_AGENTS}
    errors: list[str] = []
    for number, row in enumerate(golden, start=1):
        predictions, trial_errors = await predict_trial(row["nct_id"])
        errors += trial_errors
        for agent, (label, _) in TRIAL_AGENTS.items():
            expected = row["labels"][label]
            pairs[agent].append((expected, predictions[agent]))
            if expected != predictions[agent]:
                predicted = predictions[agent]
                print(f"  miss {row['nct_id']} {agent}: label {expected}, predicted {predicted}")
        print(f"[{number}/{len(golden)}] {row['nct_id']} done", flush=True)

    per_agent = {}
    for agent, agent_pairs in pairs.items():
        counts = confusion(agent_pairs)
        per_agent[agent] = {
            **counts,
            **precision_recall_f1(counts["tp"], counts["fp"], counts["fn"]),
            "positives": counts["tp"] + counts["fn"],
        }
    f1_scores = [scores["f1"] for scores in per_agent.values() if scores["f1"] is not None]
    metrics = {
        "per_agent": per_agent,
        "mean_f1": sum(f1_scores) / len(f1_scores) if f1_scores else None,
        "agent_errors": errors,
        "positive_confidence": POSITIVE_CONFIDENCE,
    }
    await insert_eval_run("trials", models_used(), len(golden), metrics)

    print(f"\n{'agent':16} positives  tp fp fn tn  precision recall    f1")
    for agent, s in per_agent.items():
        print(f"{agent:16} {s['positives']:9} {s['tp']:3} {s['fp']:2} {s['fn']:2} {s['tn']:2}"
              f"      {fmt(s['precision'])}  {fmt(s['recall'])} {fmt(s['f1'])}")  # fmt: skip
    print(f"mean F1 (agents where defined): {fmt(metrics['mean_f1'])}; agent errors: {len(errors)}")
    return metrics


async def run_routing() -> dict:
    tasks = load("routing.jsonl")
    results = []
    for row in tasks:
        decision, _, _ = await route(row["task"], re.findall(r"NCT\d{8}", row["task"].upper()))
        predicted = set(decision.agents) if decision.in_scope else set()
        expected = set(row["expected_agents"])
        results.append((expected == predicted, jaccard(expected, predicted)))
        if expected != predicted:
            print(f"  miss: {row['task'][:70]}")
            print(f"        expected {sorted(expected)}, got {sorted(predicted)}")
    metrics = {
        "accuracy": sum(exact for exact, _ in results) / len(results),
        "mean_jaccard": sum(score for _, score in results) / len(results),
        "correct": sum(exact for exact, _ in results),
    }
    await insert_eval_run("routing", models_used(), len(tasks), metrics)
    print(
        f"\nrouting: {metrics['correct']}/{len(tasks)} exact (accuracy {metrics['accuracy']:.2f}), "
        f"mean Jaccard {metrics['mean_jaccard']:.2f}"
    )
    return metrics


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run_eval")
    parser.add_argument("--suite", choices=["trials", "routing", "all"], default="all")
    args = parser.parse_args()
    configure_logging()
    try:
        if args.suite in ("routing", "all"):
            await run_routing()
        if args.suite in ("trials", "all"):
            await run_trials()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
