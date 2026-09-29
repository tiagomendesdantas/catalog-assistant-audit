"""Deterministic grading. No model is involved in scoring.

Outcomes:
    correct        answered, and the answer matches the record
    wrong          answered with a value that does not match the record
    abstained      said it cannot answer although the record has the answer
    unsupported    answered although the record does not contain the answer
    held_back      correctly said it cannot answer (record has no answer)
    routed         the evidence check sent the answer to human review (configuration C only)
    failed         refusal, malformed output or API error; reported separately, never dropped
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CANNOT = "CANNOT_ANSWER"
NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Grade:
    outcome: str
    parsed: str | None


def _number(text: str) -> float | None:
    m = NUMBER.search(text or "")
    return float(m.group().replace(",", ".")) if m else None


def _numbers_match(pred: float, truth: float) -> bool:
    return abs(pred - truth) <= max(0.02 * abs(truth), 0.05)


def parse_answer(family: str, attribute: str, answer: str) -> str | None:
    answer = (answer or "").strip()
    if family == "nutrition":
        n = _number(answer)
        return None if n is None else f"{n:g}"
    if attribute == "nutri_score_grade":
        m = re.search(r"\b([A-Ea-e])\b", answer)
        return m.group(1).upper() if m else None
    if attribute == "nova_group":
        m = re.search(r"\b([1-4])\b", answer)
        return m.group(1) if m else None
    low = answer.lower()
    if re.match(r"^(yes|true)\b", low):
        return "yes"
    if re.match(r"^(no|false)\b", low):
        return "no"
    return None


def grade(family: str, attribute: str, expected: str, status: str | None, answer: str | None,
          routed: bool = False) -> Grade:
    if status is None:
        return Grade("failed", None)
    if routed:
        return Grade("routed", None)
    answered = status == "answered"
    if expected == CANNOT:
        return Grade("unsupported" if answered else "held_back", None)
    if not answered:
        return Grade("abstained", None)
    parsed = parse_answer(family, attribute, answer or "")
    if parsed is None:
        return Grade("wrong", None)
    if family == "nutrition":
        return Grade("correct" if _numbers_match(float(parsed), float(expected)) else "wrong", parsed)
    return Grade("correct" if parsed == expected else "wrong", parsed)
