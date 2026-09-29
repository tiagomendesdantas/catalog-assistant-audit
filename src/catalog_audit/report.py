"""Score a run: grade every reply, then estimate rates by stratum and pooled, per configuration and
per context condition (clean record, or search results with two similar products).

Configuration C is reported twice: as the model answered ("C") and after the evidence check routes
unverifiable answers to review ("C + check").
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from catalog_audit.assistant import evidence_holds, parse_message
from catalog_audit.catalog import english_tags, load, render
from catalog_audit.estimate import stratified
from catalog_audit.grading import _numbers_match, grade, parse_answer
from catalog_audit.guard import UnknownPrice, call_cost_usd
from catalog_audit.questions import ALLERGENS, CONDITIONS, Question, read

ANSWERABLE = ["nutrition_present", "score_present", "allergen_yes", "allergen_no"]
UNANSWERABLE = ["nutrition_missing", "score_missing", "allergen_missing"]


def attribute_value(product: dict[str, Any], family: str, attribute: str) -> str | None:
    """What this product's record says about the attribute, or None when it says nothing."""
    if family == "nutrition":
        v = (product.get("nutrition_100g") or {}).get(attribute)
        return None if v is None else f"{v['value']:g}"
    if attribute == "nutri_score_grade":
        return (product.get("nutriscore_grade") or "").upper() or None
    if attribute == "nova_group":
        return None if product.get("nova_group") is None else str(int(product["nova_group"]))
    declared = set(english_tags(product.get("allergens_tags")))
    if not declared:
        return None
    return "yes" if ALLERGENS[attribute][0] in declared else "no"


def matches_neighbor(q: Question, parsed: str | None, catalog: dict[str, dict[str, Any]]) -> bool:
    """True when a wrong or unsupported answer equals what another product in the context says.
    For yes/no allergen answers a match can be coincidence; for numbers and grades it rarely is."""
    if parsed is None:
        return False
    for code in q.context:
        if code == q.code:
            continue
        value = attribute_value(catalog[code], q.family, q.attribute)
        if value is None:
            continue
        if q.family == "nutrition":
            if _numbers_match(float(parsed), float(value)):
                return True
        elif parsed == value:
            return True
    return False


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
            parsed = parse_answer(q.family, q.attribute, answer or "") if status == "answered" else None
            row = {
                "config": config, "qid": qid, "base_qid": qid.rsplit("-", 1)[0],
                "condition": q.condition, "stratum": q.stratum, "weight": q.weight,
                "outcome": base.outcome, "parsed": parsed,
                "matches_neighbor": base.outcome in ("wrong", "unsupported")
                and matches_neighbor(q, parsed, catalog),
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
    """Per-condition summaries, plus the paired effect of retrieval noise on each configuration.

    model: the model requested for the run. Responses name a dated snapshot, prices use the alias.
    """
    population = {q.stratum: q.stratum_pairs for q in questions if q.split == split}
    present = [c for c in CONDITIONS if any(r["condition"] == c for r in rows)]
    out: dict[str, Any] = {
        "population_pairs": population,
        "conditions": {c: summarise_condition([r for r in rows if r["condition"] == c], population, model)
                       for c in present},
    }
    if set(present) == set(CONDITIONS):
        out["retrieval_effect"] = {
            config: {
                "unsupported_when_not_in_record": condition_difference(
                    rows, config, UNANSWERABLE, population, {"unsupported"}),
                "accuracy_when_answerable": condition_difference(
                    rows, config, ANSWERABLE, population, {"correct"}),
            }
            for config in sorted({r["config"] for r in rows})
        }
    return out


def condition_difference(rows: list[dict[str, Any]], config: str, strata: list[str],
                         population: dict[str, int], outcomes: set[str]) -> dict[str, Any] | None:
    """Rate(retrieval) - rate(clean) for one configuration, paired on the same questions."""
    clean = {r["base_qid"]: r for r in rows if r["config"] == config and r["condition"] == "clean"}
    noisy = {r["base_qid"]: r for r in rows if r["config"] == config and r["condition"] == "retrieval"}
    groups: dict[str, tuple[list[float], list[float]]] = {}
    for h in strata:
        keys = [k for k in noisy if k in clean and noisy[k]["stratum"] == h]
        if keys:
            groups[h] = (
                [float(noisy[k]["outcome"] in outcomes) - float(clean[k]["outcome"] in outcomes)
                 for k in keys],
                [noisy[k]["weight"] for k in keys],
            )
    if not groups:
        return None
    return stratified(groups, population, bounded=False).as_dict()


def summarise_condition(rows: list[dict[str, Any]], population: dict[str, int],
                        model: str | None) -> dict[str, Any]:
    configs = sorted({r["config"] for r in rows})
    out: dict[str, Any] = {"configs": {}}
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
            "matches_neighbor": sum(1 for r in sub if r.get("matches_neighbor")),
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
    """Pick test questions where the configurations disagree, deterministically by question id.
    In the retrieval condition, answers that match another product's record come first."""
    by_q: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        by_q[r["qid"]][r["config"]] = r
    q_by_id = {q.qid: q for q in questions}
    chosen: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        for stratum in ANSWERABLE + UNANSWERABLE:
            candidates = [
                qid for qid in sorted(by_q)
                if q_by_id[qid].stratum == stratum and q_by_id[qid].condition == condition
                and {"A", "C+check"} <= set(by_q[qid])
                and by_q[qid]["A"]["outcome"] != by_q[qid]["C+check"]["outcome"]
            ]
            candidates.sort(key=lambda qid: not any(r.get("matches_neighbor")
                                                    for r in by_q[qid].values()))
            for qid in candidates[:per_stratum]:
                q = q_by_id[qid]
                product = catalog[q.code]
                chosen.append({
                    "qid": qid, "code": q.code, "product_name": product["product_name"],
                    "condition": condition, "question": q.text, "stratum": stratum,
                    "record_says": record_says(q, product),
                    "also_in_context": [catalog[c]["product_name"] for c in q.context if c != q.code],
                    "answers": {c: {"outcome": r["outcome"], "reply": r.get("reply"),
                                    "matches_neighbor": r.get("matches_neighbor", False)}
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
