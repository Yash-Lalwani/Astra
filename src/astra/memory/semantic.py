"""Semantic memory: facts about sponsors, computed by SQL from the studies table."""

from astra.queries import sponsors


async def compute_sponsor_profiles() -> None:
    """Recompute every sponsor profile. Runs once at the end of ingestion.

    compliance_rate = results_posted / applicable_completed, NULL below 3 applicable completed
    trials (insufficient data). It is the sponsor's credibility measure used by track_record.
    """
    await sponsors.recompute_profiles()
