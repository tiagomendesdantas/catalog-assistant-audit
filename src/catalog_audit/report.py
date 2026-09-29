"""Score a run: grade every reply, then estimate rates by stratum and pooled, per configuration.

Configuration C is reported twice: as the model answered ("C") and after the evidence check routes
unverifiable answers to review ("C + check").
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from catalog_audit.assistant import evidence_holds, parse_message
from catalog_audit.catalog import load, render
from catalog_audit.estimate import stratified
from catalog_audit.grading import grade
from catalog_audit.guard import UnknownPrice, call_cost_usd
from catalog_audit.questions import Question, read

ANSWERABLE = ["nutrition_present", "score_present", "allergen_yes", "allergen_no"]
UNANSWERABLE = ["nutrition_missing", "score_missing", "allergen_missing"]


def grade_run(raw_path: Path, questions: list[Question],
              catalog: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_qid = {q.qid: q for q in questions}
    catalog = catalog if catalog is not None else load()
    rows: list[dict[str, Any]] = []
    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            config, qid = item["custom_id"].split("-", 1)
            q = by_qid[qid]
            reply = parse_message(item["message"]) if item["type"] == "succeeded" else None
            status = reply.status if reply else None
            answer = reply.answer if reply else None
            base = grade(q.family, q.attribute, q.expected, status, answer)
            row = {
                "config": config, "qid": qid, "stratum": q.stratum, "weight": q.weight,
                "outcome": base.outcome, "parsed": base.parsed,
                "stop_reason": reply.stop_reason if reply else item["type"],
                "model": reply.served_by if reply else None,
                "input_tokens": reply.input_tokens if reply else 0,
                "output_tokens": reply.output_tokens if reply else 0,
                "answer": answer, "reply": reply.reply if reply else None,
            }
            rows.append(row)
            if config == "C" and reply is not None and status is not None:
                holds = evidence_holds(render(catalog[q.code]), reply, q.family)
                checked = grade(q.family, q.attribute, q.expected, status, answer, routed=not holds)
                rows.append({**row, "config": "C+check", "outcome": checked.outcome,
                             "would_have_been": base.outcome})
            elif config == "C":
                rows.append({**row, "config": "C+check"})
    return rows


def _rate(rows: list[dict[str, Any]], strata: list[str], population: dict[str, int],
          outcomes: set[str]) -> dict[str, Any] | None:
    groups: dict[str, tuple[list[float], list[float]]] = {}
    for h in strata:
        sub = [r for r in rows if r["stratum"] == h]
        if sub:
            groups[h] = ([1.0 if r["outcome"] in outcomes else 0.0 for r in sub],
                         [r["weight"] for r in sub])
    if not groups:
        return None
    return stratified(groups, population).as_dict()


def paired_difference(rows: list[dict[str, Any]], config: str, baseline: str, strata: list[str],
                      population: dict[str, int], outcomes: set[str]) -> dict[str, Any] | None:
    """Rate(config) - rate(baseline) on the same questions, with a paired interval."""
    a = {r["qid"]: r for r in rows if r["config"] == config}
    b = {r["qid"]: r for r in rows if r["config"] == baseline}
    groups: dict[str, tuple[list[float], list[float]]] = {}
    for h in strata:
        qids = [q for q in a if q in b and a[q]["stratum"] == h]
        if qids:
            groups[h] = (
                [float(a[q]["outcome"] in outcomes) - float(b[q]["outcome"] in outcomes) for q in qids],
                [a[q]["weight"] for q in qids],
            )
    if not groups:
        return None
    return stratified(groups, population, bounded=False).as_dict()


def _cost(model: str | None, rows: list[dict[str, Any]]) -> float | None:
    """Total standard-price cost of the rows, or None when the model has no verified price."""
    if not model or not rows:
        return None
    try:
        return sum(call_cost_usd(model, r["input_tokens"], r["output_tokens"]) for r in rows)
    except UnknownPrice:
        return None


def summarise(rows: list[dict[str, Any]], questions: list[Question], split: str,
              model: str | None = None) -> dict[str, Any]:
    """model: the model requested for the run. Responses name a dated snapshot, prices use the alias."""
    population = {q.stratum: q.stratum_pairs for q in questions if q.split == split}
    configs = sorted({r["config"] for r in rows})
    out: dict[str, Any] = {"configs": {}, "population_pairs": population}
    for c in configs:
        sub = [r for r in rows if r["config"] == c]
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in sub:
            counts[r["stratum"]][r["outcome"]] += 1
        billed = [r for r in sub if r["config"] != "C+check"]
        served = next((r["model"] for r in sub if r["model"]), None)
        cost = _cost(model, billed)
        out["configs"][c] = {
            "model": model,
            "served_by": served,
            "questions": len(sub),
            "headline": {
                "accuracy_when_answerable": _rate(sub, ANSWERABLE, population, {"correct"}),
                "abstained_when_answerable": _rate(sub, ANSWERABLE, population, {"abstained"}),
                "unsupported_when_not_in_record": _rate(sub, UNANSWERABLE, population, {"unsupported"}),
                "routed_to_review": _rate(sub, ANSWERABLE + UNANSWERABLE, population, {"routed"}),
            },
            "by_stratum": {
                h: {
                    "correct": _rate(sub, [h], population, {"correct"}),
                    "wrong": _rate(sub, [h], population, {"wrong"}),
                    "abstained": _rate(sub, [h], population, {"abstained"}),
                    "unsupported": _rate(sub, [h], population, {"unsupported"}),
                    "held_back": _rate(sub, [h], population, {"held_back"}),
                    "routed": _rate(sub, [h], population, {"routed"}),
                    "failed": counts[h]["failed"],
                    "counts": dict(counts[h]),
                }
                for h in ANSWERABLE + UNANSWERABLE
                if counts[h]
            },
            "failed": sum(1 for r in sub if r["outcome"] == "failed"),
            "cost_usd_standard_per_1000": (cost / len(billed) * 1000) if billed and cost else None,
        }
        if c != "A" and "A" in configs:
            out["configs"][c]["versus_A"] = {
                "accuracy_when_answerable": paired_difference(
                    rows, c, "A", ANSWERABLE, population, {"correct"}),
                "unsupported_when_not_in_record": paired_difference(
                    rows, c, "A", UNANSWERABLE, population, {"unsupported"}),
            }
        if c == "C+check":
            routed = [r for r in sub if r["outcome"] == "routed"]
            caught = defaultdict(int)
            for r in routed:
                caught[r.get("would_have_been", "unknown")] += 1
            out["configs"][c]["routed_would_have_been"] = dict(caught)
    return out


def record_says(q: Question, product: dict[str, Any]) -> str:
    from catalog_audit.catalog import NUTRIENT_LABELS, unit_of

    if q.expected == "CANNOT_ANSWER":
        what = NUTRIENT_LABELS.get(q.attribute, q.attribute).replace("_", " ")
        return f"nothing about {what}" if q.family != "allergen" else "no allergen or ingredient information"
    if q.family == "nutrition":
        return f"{NUTRIENT_LABELS[q.attribute]}: {q.expected} {unit_of(q.attribute)} per 100 g"
    if q.family == "score":
        return f"{q.attribute.replace('_', ' ')}: {q.expected}"
    declared = render(product).get("allergens_declared", [])
    if q.expected == "yes":
        return f"{q.attribute} is a declared allergen"
    return f"declared allergens: {', '.join(declared)} ({q.attribute} is not among them)"


def build_examples(rows: list[dict[str, Any]], questions: list[Question],
                   catalog: dict[str, dict[str, Any]], per_stratum: int = 2) -> list[dict[str, Any]]:
    """Pick test questions where the configurations disagree, deterministically by question id."""
    by_q: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        by_q[r["qid"]][r["config"]] = r
    q_by_id = {q.qid: q for q in questions}
    chosen: list[dict[str, Any]] = []
    for stratum in ANSWERABLE + UNANSWERABLE:
        picks = [
            qid for qid in sorted(by_q)
            if q_by_id[qid].stratum == stratum
            and {"A", "C+check"} <= set(by_q[qid])
            and by_q[qid]["A"]["outcome"] != by_q[qid]["C+check"]["outcome"]
        ][:per_stratum]
        for qid in picks:
            q = q_by_id[qid]
            product = catalog[q.code]
            chosen.append({
                "qid": qid, "code": q.code, "product_name": product["product_name"],
                "question": q.text, "stratum": stratum, "record_says": record_says(q, product),
                "answers": {c: {"outcome": r["outcome"], "reply": r.get("reply")}
                            for c, r in by_q[qid].items()},
            })
    return chosen


def score(run_dir: Path, questions_path: Path, split: str, model: str | None = None) -> dict[str, Any]:
    questions = read(questions_path)
    rows = grade_run(run_dir / "raw.jsonl", [q for q in questions if q.split == split])
    summary = summarise(rows, questions, split, model)
    (run_dir / "graded.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
