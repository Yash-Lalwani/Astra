"""Input protection (guardrail 1): checks on the user's task before any model sees it.
The supervisor's in_scope decision is the third check."""

from astra.guardrails.injection import injection_match

MIN_TASK_CHARS = 3
MAX_TASK_CHARS = 500


def check_task(task: str) -> str | None:
    """Why the task is blocked, or None when it may run."""
    if not MIN_TASK_CHARS <= len(task.strip()) <= MAX_TASK_CHARS:
        return f"task must be {MIN_TASK_CHARS}-{MAX_TASK_CHARS} characters"
    if injection_match(task):
        return "task matches a prompt-injection pattern"
    return None
