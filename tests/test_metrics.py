import pytest

from evals.metrics import confusion, jaccard, precision_recall_f1


def test_confusion_counts():
    pairs = [(True, True), (True, False), (False, True), (False, False), (True, True)]
    assert confusion(pairs) == {"tp": 2, "fp": 1, "fn": 1, "tn": 1}


def test_precision_recall_f1():
    scores = precision_recall_f1(tp=2, fp=1, fn=1)
    assert scores["precision"] == pytest.approx(2 / 3)
    assert scores["recall"] == pytest.approx(2 / 3)
    assert scores["f1"] == pytest.approx(2 / 3)


def test_undefined_values_are_none():
    assert precision_recall_f1(tp=0, fp=0, fn=3) == {"precision": None, "recall": 0.0, "f1": None}
    assert precision_recall_f1(tp=0, fp=2, fn=0) == {"precision": 0.0, "recall": None, "f1": None}
    assert precision_recall_f1(tp=0, fp=1, fn=1)["f1"] is None  # precision + recall == 0


@pytest.mark.parametrize(
    ("expected", "predicted", "score"),
    [
        ({"a", "b"}, {"a", "b"}, 1.0),
        ({"a", "b"}, {"a"}, 0.5),
        ({"a"}, {"b"}, 0.0),
        (set(), set(), 1.0),
        (set(), {"a"}, 0.0),
    ],
)
def test_jaccard(expected, predicted, score):
    assert jaccard(expected, predicted) == score
