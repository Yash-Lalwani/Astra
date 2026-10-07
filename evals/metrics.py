"""Pure scoring functions for the evals."""


def confusion(pairs: list[tuple[bool, bool]]) -> dict[str, int]:
    """Counts from (label, predicted) pairs."""
    return {
        "tp": sum(label and predicted for label, predicted in pairs),
        "fp": sum(not label and predicted for label, predicted in pairs),
        "fn": sum(label and not predicted for label, predicted in pairs),
        "tn": sum(not label and not predicted for label, predicted in pairs),
    }


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    """None where a value is undefined (no predicted positives, or no labelled positives)."""
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def jaccard(expected: set[str], predicted: set[str]) -> float:
    """Overlap of two agent sets; two empty sets (a correctly refused task) count as 1.0."""
    if not expected and not predicted:
        return 1.0
    return len(expected & predicted) / len(expected | predicted)
