import uuid

from astra.db import execute_many, fetch_all, fetch_one


async def seed_rules(rules: list[tuple[str, str]]) -> None:
    """rules: (agent, rule_text). Existing rules are left alone, so seeding is idempotent.
    clock_timestamp() (not now(), which is fixed per transaction) keeps the given order."""
    await execute_many(
        """
        INSERT INTO agent_rules (agent, rule_text, source, created_at)
        VALUES (%s, %s, 'default', clock_timestamp())
        ON CONFLICT (agent, rule_text) DO NOTHING
        """,
        rules,
    )


async def rules_for(agent: str) -> list[dict]:
    return await fetch_all(
        """
        SELECT rule_id, agent, rule_text, source, learned_from_signal_id, reviewer_reason,
               created_at
        FROM agent_rules WHERE agent = %s
        ORDER BY created_at, rule_id
        """,
        (agent,),
    )


async def insert_learned_rule(
    agent: str, rule_text: str, signal_id: uuid.UUID, reviewer_reason: str
) -> dict | None:
    """The new rule's row, or None when the agent already has this exact rule."""
    return await fetch_one(
        """
        INSERT INTO agent_rules (agent, rule_text, source, learned_from_signal_id, reviewer_reason)
        VALUES (%s, %s, 'learned', %s, %s)
        ON CONFLICT (agent, rule_text) DO NOTHING
        RETURNING rule_id, rule_text
        """,
        (agent, rule_text, signal_id, reviewer_reason),
    )


async def rule_counts() -> dict[str, int]:
    rows = await fetch_all("SELECT agent, count(*) AS rules FROM agent_rules GROUP BY agent")
    return {row["agent"]: row["rules"] for row in rows}
