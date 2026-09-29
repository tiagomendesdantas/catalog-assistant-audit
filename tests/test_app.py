import json

import pytest
from conftest import TEST_MODEL, completion
from fastapi.testclient import TestClient

from catalog_audit import app as app_module
from catalog_audit.guard import Limits, SpendGuard

CATALOG = {
    "111": {
        "code": "111", "product_name": "Tomato Salsa", "brands": "Acme", "quantity": "16 oz",
        "categories_tags": ["en:sauces"], "ingredients_text": "tomatoes, onions, salt",
        "allergens_tags": [], "traces_tags": [], "labels_tags": [], "nutriscore_grade": "b",
        "nova_group": 3, "nutrition_100g": {"salt": {"value": 1.2, "unit": "g"}},
    },
}


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return completion(json.dumps(self.payload))


class FakeClient:
    def __init__(self, payload):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(payload)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "catalog", lambda: CATALOG)
    monkeypatch.setattr(app_module, "_INDEX", None)
    monkeypatch.setattr(app_module, "guard", SpendGuard(Limits(2, 20, 2.0)))
    monkeypatch.setenv("OPENAI_MODEL", TEST_MODEL)
    return TestClient(app_module.app)


def live(monkeypatch, payload):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    fake = FakeClient(payload)
    monkeypatch.setattr(app_module, "_client", fake)
    return fake


def test_search_and_product(client):
    hits = client.get("/api/products", params={"q": "salsa"}).json()
    assert hits == [{"code": "111", "name": "Tomato Salsa", "brand": "Acme"}]
    body = client.get("/api/products/111").json()
    assert body["record"]["nutrition_per_100g"] == {"salt": "1.2 g"}
    assert body["source"].endswith("/product/111")
    assert client.get("/api/products/999").status_code == 404


def test_live_questions_are_off_without_a_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/api/ask", json={"code": "111", "question": "How much salt?"})
    assert r.status_code == 503


def test_live_questions_are_off_for_a_model_without_a_verified_price(client, monkeypatch):
    live(monkeypatch, {})
    monkeypatch.setenv("OPENAI_MODEL", "model-without-a-verified-price")
    assert client.get("/healthz").json()["live"] is False
    r = client.post("/api/ask", json={"code": "111", "question": "How much salt?"})
    assert r.status_code == 503


def test_answer_with_matching_evidence(client, monkeypatch):
    fake = live(monkeypatch, {"status": "answered", "answer": "1.2 g", "reply": "1.2 g per 100 g.",
                              "evidence": [{"field": "nutrition_per_100g.salt", "value": "1.2 g"}]})
    body = client.post("/api/ask", json={"code": "111", "question": "How much salt?"}).json()
    assert body["outcome"] == "answered" and body["evidence_holds"] is True
    call = fake.chat.completions.calls[0]
    assert call["model"] == TEST_MODEL and call["response_format"]["json_schema"]["strict"] is True
    assert body["cost_usd"] > 0


def test_answer_citing_a_missing_field_goes_to_review(client, monkeypatch):
    live(monkeypatch, {"status": "answered", "answer": "3 g", "reply": "About 3 g.",
                       "evidence": [{"field": "nutrition_per_100g.fiber", "value": "3 g"}]})
    body = client.post("/api/ask", json={"code": "111", "question": "How much fiber?"}).json()
    assert body["outcome"] == "routed_to_review"


def test_rate_limit_returns_429(client, monkeypatch):
    live(monkeypatch, {"status": "cannot_answer", "answer": "", "reply": "Not listed.", "evidence": []})
    for _ in range(2):
        assert client.post("/api/ask", json={"code": "111", "question": "Any fiber?"}).status_code == 200
    r = client.post("/api/ask", json={"code": "111", "question": "Any fiber?"})
    assert r.status_code == 429 and "limit" in r.json()["detail"]


def test_question_length_is_capped(client, monkeypatch):
    live(monkeypatch, {})
    r = client.post("/api/ask", json={"code": "111", "question": "x" * 301})
    assert r.status_code == 422
