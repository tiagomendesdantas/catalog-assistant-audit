import json

import pytest
from conftest import TEST_MODEL, completion

from catalog_audit.assistant import Reply, evidence_holds, parse_message, request_params, schema
from catalog_audit.catalog import render

PRODUCT = {
    "code": "123",
    "product_name": "Oat Crunch Cereal",
    "brands": "Acme",
    "quantity": "500 g",
    "categories_tags": ["en:breakfasts", "en:cereals"],
    "ingredients_text": "whole grain oats, sugar, salt",
    "allergens_tags": ["en:gluten"],
    "traces_tags": ["en:nuts"],
    "labels_tags": [],
    "nutriscore_grade": "c",
    "nova_group": 4,
    "nutrition_100g": {"sugars": {"value": 12.5, "unit": "g"}, "salt": {"value": 0.8, "unit": "g"}},
}
RECORD = render(PRODUCT)


def reply(status="answered", answer="", evidence=None):
    return Reply(status, answer, "", evidence or [], "end_turn", 0, 0, None)


def test_render_omits_missing_fields_and_keeps_only_per_100g():
    assert "labels" not in RECORD
    assert RECORD["nutrition_per_100g"] == {"sugars": "12.5 g", "salt": "0.8 g"}


def test_render_uses_the_stored_unit_not_the_typed_one():
    # Open Food Facts stores salt per 100 g in grams even when a contributor typed it in mg.
    typed_in_mg = {**PRODUCT, "nutrition_100g": {"salt": {"value": 1.178, "unit": "mg"},
                                                 "energy-kcal": {"value": 529, "unit": "kJ"}}}
    assert render(typed_in_mg)["nutrition_per_100g"] == {"energy": "529 kcal", "salt": "1.178 g"}


def test_impossible_values_are_never_asked_about():
    from catalog_audit.questions import pairs_for

    bad = {**PRODUCT, "nutrition_100g": {"energy-kcal": {"value": 2800, "unit": "kcal"},
                                         "sugars": {"value": 12.5, "unit": "g"}}}
    asked = {(p.attribute, p.stratum) for p in pairs_for(bad) if p.family == "nutrition"}
    assert ("energy-kcal", "nutrition_present") not in asked
    assert ("energy-kcal", "nutrition_missing") not in asked
    assert ("sugars", "nutrition_present") in asked
    assert RECORD["allergens_declared"] == ["gluten"]
    assert RECORD["nutri_score_grade"] == "C"


def test_request_uses_strict_schema_and_low_effort():
    params = request_params("C", json.dumps(RECORD), "How much sugar?", TEST_MODEL, "low")
    fmt = params["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["required"][-1] == "evidence"
    assert params["reasoning_effort"] == "low"
    assert params["messages"][0]["role"] == "developer"
    assert "Answer only from the catalog record" in params["messages"][0]["content"]
    assert "evidence" not in schema("A")["properties"]
    baseline = request_params("A", "{}", "q", TEST_MODEL, "low")["messages"][0]["content"]
    assert "Answer only from the catalog record" not in baseline


def test_request_without_effort_and_without_model():
    assert "reasoning_effort" not in request_params("A", "{}", "q", TEST_MODEL, "")
    with pytest.raises(ValueError, match="No model"):
        request_params("A", "{}", "q", "", "low")


def test_strict_schema_lists_every_property_as_required():
    for config in "ABC":
        s = schema(config)
        assert set(s["required"]) == set(s["properties"]) and s["additionalProperties"] is False


def test_evidence_holds_for_a_faithful_quote():
    r = reply(answer="12.5 g", evidence=[{"field": "nutrition_per_100g.sugars", "value": "12.5 g"}])
    assert evidence_holds(RECORD, r, "nutrition")


def test_evidence_fails_for_a_field_that_is_not_in_the_record():
    r = reply(answer="3 g", evidence=[{"field": "nutrition_per_100g.fiber", "value": "3 g"}])
    assert not evidence_holds(RECORD, r, "nutrition")


def test_evidence_fails_when_answer_number_differs_from_the_quote():
    r = reply(answer="0.8 g", evidence=[{"field": "nutrition_per_100g.sugars", "value": "12.5 g"}])
    assert not evidence_holds(RECORD, r, "nutrition")


def test_list_quotes_in_json_or_plain_form_and_subsets():
    record = {**RECORD, "allergens_declared": ["eggs", "milk", "soybeans"]}
    for quote in ['["eggs", "milk", "soybeans"]', "eggs, milk, soybeans", "milk", '["milk"]']:
        r = reply(answer="yes", evidence=[{"field": "allergens_declared", "value": quote}])
        assert evidence_holds(record, r, "allergen"), quote
    for quote in ['["milk", "fish"]', "fish", "[]"]:
        r = reply(answer="yes", evidence=[{"field": "allergens_declared", "value": quote}])
        assert not evidence_holds(record, r, "allergen"), quote


def test_base_prompt_defines_undeclared_allergens_for_every_configuration():
    for config in "ABC":
        system = request_params(config, "{}", "q", TEST_MODEL, "low")["messages"][0]["content"]
        assert "the answer is no: it is not declared" in system


def test_evidence_list_fields_and_cannot_answer():
    r = reply(answer="yes", evidence=[{"field": "allergens_declared", "value": "gluten"}])
    assert evidence_holds(RECORD, r, "allergen")
    assert not evidence_holds(RECORD, reply(answer="yes"), "allergen")  # answered without evidence
    assert evidence_holds(RECORD, reply(status="cannot_answer"), "allergen")


def test_parse_message_handles_refusal_truncation_and_bad_json():
    ok = completion('{"status": "answered", "answer": "C", "reply": "C."}', completion_tokens=7)
    parsed = parse_message(ok)
    assert parsed.status == "answered" and parsed.answer == "C" and parsed.output_tokens == 7
    assert parsed.input_tokens == 900 and parsed.served_by.startswith(TEST_MODEL)
    refused = parse_message(completion("", refusal="I can't help with that."))
    assert refused.status is None and refused.stop_reason == "refusal"
    truncated = parse_message(completion('{"status": "ans', finish_reason="length"))
    assert truncated.status is None and truncated.stop_reason == "length"
    assert parse_message(completion("not json")).status is None
