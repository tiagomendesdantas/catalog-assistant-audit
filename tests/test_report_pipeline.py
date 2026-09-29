"""End-to-end plumbing on synthetic replies: questions -> raw batch lines -> graded -> summary."""

import json

from conftest import TEST_MODEL, completion

from catalog_audit.questions import build
from catalog_audit.report import attribute_value, grade_run, summarise


def product(code, sugar=None, grade=None, allergens=(), ingredients="water, sugar"):
    return {
        "code": code, "product_name": f"Product {code}", "brands": None, "quantity": None,
        "categories_tags": [], "ingredients_text": ingredients, "allergens_tags": list(allergens),
        "traces_tags": [], "labels_tags": [], "nutriscore_grade": grade, "nova_group": None,
        "nutrition_100g": {"sugars": {"value": sugar, "unit": "g"}} if sugar is not None else {},
    }


CATALOG = {
    **{f"p{i:03d}": product(f"p{i:03d}", sugar=5.0 + i, grade="b", allergens=["en:milk"])
       for i in range(60)},
    **{f"q{i:03d}": product(f"q{i:03d}", ingredients="") for i in range(60)},
}
# Every product's search neighbours are two p-products, which do list sugars and a grade.
NEIGHBORS = {code: ["p000", "p001"] if code not in ("p000", "p001") else ["p002", "p003"]
             for code in CATALOG}


def message(status, answer, evidence=None):
    body = {"status": status, "answer": answer, "reply": "..."}
    if evidence is not None:
        body["evidence"] = evidence
    return completion(json.dumps(body), prompt_tokens=800, completion_tokens=300)


def fake_reply(config, q):
    """A fills gaps (from a neighbour when one is in context); B and C say the catalog doesn't list it."""
    if q.expected == "CANNOT_ANSWER":
        if config != "A":
            return message("cannot_answer", "")
        neighbour = next((c for c in q.context if c != q.code), None)
        borrowed = neighbour and attribute_value(CATALOG[neighbour], q.family, q.attribute)
        return message("answered", borrowed or "3 g")
    if config == "C" and q.family == "nutrition":
        # Correct number but cites a field that does not exist: the check must route it.
        return message("answered", q.expected, [{"field": "nutrition_per_100g.fiber", "value": q.expected}])
    ev = [] if config != "C" else [{"field": "product_name", "value": q.code}]
    return message("answered", q.expected, ev)


def test_pipeline_grades_and_summarises(tmp_path):
    questions, frame = build(CATALOG, NEIGHBORS)
    assert questions, frame
    assert {q.condition for q in questions} == {"clean", "retrieval"}
    split = "test"
    qs = [q for q in questions if q.split == split]
    retrieval = [q for q in qs if q.condition == "retrieval"]
    assert all(len(q.context) == 3 and q.code in q.context for q in retrieval)
    assert len({q.context.index(q.code) for q in retrieval}) > 1  # the target's position varies

    raw = tmp_path / "raw.jsonl"
    with raw.open("w") as fh:
        for config in "ABC":
            for q in qs:
                fh.write(json.dumps({"custom_id": f"{config}-{q.qid}", "type": "succeeded",
                                     "message": fake_reply(config, q)}) + "\n")
    rows = grade_run(raw, qs, catalog=CATALOG)
    summary = summarise(rows, questions, split, TEST_MODEL)
    unpriced = summarise(rows, questions, split, "unpriced")
    assert unpriced["conditions"]["clean"]["configs"]["A"]["cost_usd_standard_per_1000"] is None

    for condition in ("clean", "retrieval"):
        configs = summary["conditions"][condition]["configs"]
        a, b = configs["A"]["headline"], configs["B"]["headline"]
        assert a["unsupported_when_not_in_record"]["rate"] == 1.0
        assert b["unsupported_when_not_in_record"]["rate"] == 0.0
        assert b["accuracy_when_answerable"]["rate"] == 1.0
        assert configs["B"]["versus_A"]["unsupported_when_not_in_record"]["rate"] == -1.0
        assert configs["C+check"]["routed_would_have_been"].get("correct", 0) > 0
        assert configs["A"]["cost_usd_standard_per_1000"] > 0

    # Borrowed values are only possible, and only flagged, when neighbours are in the context.
    assert summary["conditions"]["clean"]["configs"]["A"]["matches_neighbor"] == 0
    assert summary["conditions"]["retrieval"]["configs"]["A"]["matches_neighbor"] > 0
    effect = summary["retrieval_effect"]["A"]["unsupported_when_not_in_record"]
    assert effect["rate"] == 0.0  # A invents in both conditions; only the source changes
