"""End-to-end plumbing on synthetic replies: questions -> raw batch lines -> graded -> summary."""

import json

from conftest import TEST_MODEL, completion

from catalog_audit.questions import build
from catalog_audit.report import grade_run, summarise


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


def message(status, answer, evidence=None):
    body = {"status": status, "answer": answer, "reply": "..."}
    if evidence is not None:
        body["evidence"] = evidence
    return completion(json.dumps(body), prompt_tokens=800, completion_tokens=300)


def fake_reply(config, q):
    """A answers everything from the record or invents; B and C abstain when the field is missing."""
    if q.expected == "CANNOT_ANSWER":
        if config == "A":
            return message("answered", "3 g")
        return message("cannot_answer", "")
    if config == "C" and q.family == "nutrition":
        # Correct number but cites a field that does not exist: the check must route it.
        return message("answered", q.expected, [{"field": "nutrition_per_100g.fiber", "value": q.expected}])
    ev = [] if config != "C" else [{"field": "product_name", "value": q.code}]
    return message("answered", q.expected, ev)


def test_pipeline_grades_and_summarises(tmp_path):
    questions, frame = build(CATALOG)
    assert questions, frame
    split = "test"
    qs = [q for q in questions if q.split == split]
    raw = tmp_path / "raw.jsonl"
    with raw.open("w") as fh:
        for config in "ABC":
            for q in qs:
                fh.write(json.dumps({"custom_id": f"{config}-{q.qid}", "type": "succeeded",
                                     "message": fake_reply(config, q)}) + "\n")
    rows = grade_run(raw, qs, catalog=CATALOG)
    summary = summarise(rows, questions, split, TEST_MODEL)
    assert summarise(rows, questions, split, "unpriced")["configs"]["A"]["cost_usd_standard_per_1000"] is None
    a, b = summary["configs"]["A"]["headline"], summary["configs"]["B"]["headline"]
    assert a["unsupported_when_not_in_record"]["rate"] == 1.0
    assert b["unsupported_when_not_in_record"]["rate"] == 0.0
    assert b["accuracy_when_answerable"]["rate"] == 1.0
    diff = summary["configs"]["B"]["versus_A"]["unsupported_when_not_in_record"]
    assert diff["rate"] == -1.0
    check = summary["configs"]["C+check"]
    assert check["routed_would_have_been"].get("correct", 0) > 0  # the check also catches good answers
    assert summary["configs"]["A"]["cost_usd_standard_per_1000"] > 0
