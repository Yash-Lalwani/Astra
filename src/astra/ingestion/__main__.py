"""python -m astra.ingestion [--per-condition 200] [--groups oncology metabolic_t2d ...]"""

import argparse
import asyncio

from astra.config import CONDITION_GROUPS, configure_logging
from astra.db import close_pool
from astra.ingestion.pipeline import run_ingestion
from astra.queries import papers, sponsors, trials


async def print_summary() -> None:
    print("\ncondition_group      status                    trials  results  applicable")
    for row in await trials.counts_by_group_and_status():
        print(
            f"{row['condition_group']:<20} {row['overall_status']:<25} "
            f"{row['trials']:>6} {row['with_results']:>8} {row['applicable']:>11}"
        )
    paper_counts = await papers.paper_counts()
    print(
        f"\npapers: {paper_counts['papers']}  links: {paper_counts['links']}  "
        f"trials with papers: {paper_counts['trials_with_papers']}"
    )
    profiles = await sponsors.profile_summary()
    print(
        f"sponsors: {profiles['sponsors']}  with compliance rate: {profiles['rated']}  "
        f"avg rate: {profiles['avg_compliance_rate']}  "
        f"missing results: {profiles['missing_results']}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m astra.ingestion")
    parser.add_argument("--per-condition", type=int, default=200)
    parser.add_argument(
        "--groups", nargs="+", choices=list(CONDITION_GROUPS), default=list(CONDITION_GROUPS)
    )
    args = parser.parse_args()
    configure_logging()
    try:
        await run_ingestion(args.per_condition, args.groups)
        await print_summary()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
