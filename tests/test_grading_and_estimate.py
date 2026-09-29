import math
import random

import pytest

from catalog_audit.estimate import hajek, stratified, wilson
from catalog_audit.grading import CANNOT, grade, parse_answer


@pytest.mark.parametrize(
    "family,attribute,expected,status,answer,outcome",
    [
        ("nutrition", "sugars", "12.5", "answered", "12.5 g", "correct"),
        ("nutrition", "sugars", "12.5", "answered", "12.7", "correct"),  # within 2%
        ("nutrition", "sugars", "12.5", "answered", "13", "wrong"),
        ("nutrition", "sugars", "0", "answered", "0.04 g", "correct"),  # absolute floor
        ("nutrition", "sugars", "12.5", "cannot_answer", "", "abstained"),
        ("nutrition", "sugars", CANNOT, "answered", "about 10 g", "unsupported"),
        ("nutrition", "sugars", CANNOT, "cannot_answer", "", "held_back"),
        ("score", "nutri_score_grade", "C", "answered", "Nutri-Score C", "correct"),
        ("score", "nutri_score_grade", "C", "answered", "grade d", "wrong"),
        ("score", "nova_group", "4", "answered", "Group 4 (ultra-processed)", "correct"),
        ("allergen", "milk", "yes", "answered", "Yes, milk is declared.", "correct"),
        ("allergen", "milk", "no", "answered", "Yes.", "wrong"),
        ("allergen", "milk", "no", "answered", "Maybe", "wrong"),
        ("allergen", "milk", CANNOT, "answered", "No", "unsupported"),
        ("allergen", "milk", "yes", None, None, "failed"),
    ],
)
def test_grade(family, attribute, expected, status, answer, outcome):
    assert grade(family, attribute, expected, status, answer).outcome == outcome


def test_routed_overrides_everything():
    assert grade("nutrition", "fat", "3", "answered", "3", routed=True).outcome == "routed"


def test_parse_answer_does_not_take_a_grade_letter_from_a_word():
    assert parse_answer("score", "nutri_score_grade", "It has grade B.") == "B"
    assert parse_answer("score", "nutri_score_grade", "unknown") is None


def test_hajek_equal_weights_is_the_plain_mean():
    p, var, n_eff = hajek([1, 0, 0, 1], [2.0] * 4)
    assert p == pytest.approx(0.5)
    assert n_eff == pytest.approx(4)
    assert var == pytest.approx(4 / 3 * 4 * 4 * 0.25 / 64)


def test_stratified_interval_covers_known_rate():
    """Coverage check of the interval under the sampling design (implementation check only)."""
    rng = random.Random(7)
    truth = 0.2 * 0.7 + 0.1 * 0.3  # two strata with population shares 0.7 and 0.3
    hits, reps = 0, 400
    for _ in range(reps):
        groups = {
            "a": ([1 if rng.random() < 0.2 else 0 for _ in range(120)], [10.0] * 120),
            "b": ([1 if rng.random() < 0.1 else 0 for _ in range(120)], [5.0] * 120),
        }
        est = stratified(groups, {"a": 7000, "b": 3000})
        hits += est.low <= truth <= est.high
    assert 0.92 <= hits / reps <= 0.98


def test_all_zero_differences_do_not_report_certainty():
    est = stratified({"a": ([0.0] * 120, [1.0] * 120)}, {"a": 1000}, bounded=False)
    assert est.rate == 0.0
    assert est.low < -0.02 and est.high > 0.02
    assert est.low == pytest.approx(-est.high)


def test_all_zero_outcomes_do_not_report_certainty():
    est = stratified({"a": ([0] * 120, [1.0] * 120)}, {"a": 1000})
    assert est.rate == 0.0
    assert est.high > 0.02
    low, high = wilson(0.0, 120)
    assert low == 0.0 and math.isclose(high, est.high)
