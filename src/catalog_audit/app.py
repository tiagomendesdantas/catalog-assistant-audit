"""Web app: the product assistant demo and the audit results.

Everything a visitor sees by default is precomputed. The one live path, POST /api/ask, runs
configuration C with the evidence check, behind per-visitor and daily spend limits.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from catalog_audit.assistant import MAX_TOKENS, MODEL, evidence_holds, parse_message, request_params
from catalog_audit.catalog import load, render, render_json
from catalog_audit.guard import PRICES_PER_MTOK, Blocked, Limits, SpendGuard, call_cost_usd

LIVE_OFF = "Live questions are switched off. The examples below still work."

WEB = Path(__file__).resolve().parents[2] / "web"
OFF_PRODUCT = "https://world.openfoodfacts.org/product/{code}"

app = FastAPI(title="Catalog assistant audit", docs_url="/docs", redoc_url=None)
guard = SpendGuard(Limits(
    per_ip_per_hour=int(os.getenv("LIVE_PER_IP_PER_HOUR", "5")),
    per_ip_per_day=int(os.getenv("LIVE_PER_IP_PER_DAY", "20")),
    daily_usd=float(os.getenv("LIVE_DAILY_USD", "2.00")),
))
_client: Any = None


def client() -> Any:
    global _client
    if _client is None:
        import openai

        _client = openai.OpenAI(timeout=45.0, max_retries=1)
    return _client


def catalog() -> dict[str, dict[str, Any]]:
    return load()


def _search_index() -> list[tuple[str, str, str]]:
    return sorted(
        ((p["product_name"].lower(), code, p["product_name"]) for code, p in catalog().items()),
        key=lambda t: t[0],
    )


_INDEX: list[tuple[str, str, str]] | None = None


def live_model() -> str | None:
    """The model live questions use, or None when live questions must stay off.

    Off when there is no key, no model, or no verified price for the model: without a price the
    spend limits cannot be enforced, so the endpoint fails closed.
    """
    model = os.getenv("OPENAI_MODEL") or MODEL
    if not os.getenv("OPENAI_API_KEY") or not model or model not in PRICES_PER_MTOK:
        return None
    return model


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "products": len(catalog()), "live": live_model() is not None}


@app.get("/api/products")
def products(q: str = "", limit: int = 20) -> list[dict[str, str]]:
    global _INDEX
    if _INDEX is None:
        _INDEX = _search_index()
    needle = q.strip().lower()
    hits = [t for t in _INDEX if needle in t[0]] if needle else _INDEX[::97]
    items = catalog()
    return [
        {"code": code, "name": name, "brand": items[code].get("brands") or ""}
        for _, code, name in hits[: max(1, min(limit, 50))]
    ]


@app.get("/api/products/{code}")
def product(code: str) -> dict[str, Any]:
    item = catalog().get(code)
    if item is None:
        raise HTTPException(404, "Product not in this catalog.")
    return {"code": code, "record": render(item), "source": OFF_PRODUCT.format(code=code)}


def _static_json(name: str) -> Any:
    path = WEB / name
    if not path.exists():
        raise HTTPException(404, f"{name} has not been generated yet.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/results")
def results() -> Any:
    return _static_json("results.json")


@app.get("/api/examples")
def examples() -> Any:
    return _static_json("examples.json")


class Ask(BaseModel):
    code: str
    question: str = Field(min_length=3, max_length=300)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@app.post("/api/ask")
def ask(body: Ask, request: Request) -> JSONResponse:
    model = live_model()
    if model is None:
        raise HTTPException(503, LIVE_OFF)
    item = catalog().get(body.code)
    if item is None:
        raise HTTPException(404, "Product not in this catalog.")
    record_json = render_json(item)
    params = request_params("C", record_json, body.question, model)
    price_in, price_out = PRICES_PER_MTOK[model]
    est_in = sum(len(m["content"]) for m in params["messages"]) / 3.0 + 400
    worst = (est_in * price_in + MAX_TOKENS * price_out) / 1_000_000
    try:
        guard.reserve(_client_ip(request), worst)
    except Blocked as exc:
        return JSONResponse({"detail": str(exc)}, status_code=429)

    started = time.time()
    actual = 0.0
    try:
        completion = client().chat.completions.create(**params)
        reply = parse_message(completion)
        actual = call_cost_usd(model, reply.input_tokens, reply.output_tokens)
    except Exception as exc:  # the visitor sees a plain failure, never a made-up answer
        guard.settle(worst, actual)
        raise HTTPException(502, "The assistant did not answer. Try again, or use the examples.") from exc
    guard.settle(worst, actual)

    if reply.status is None:
        return JSONResponse({"outcome": "failed", "stop_reason": reply.stop_reason,
                             "detail": "The assistant returned no usable answer."})
    holds = evidence_holds(render(item), reply)
    outcome = ("not_in_catalog" if reply.status == "cannot_answer"
               else "answered" if holds else "routed_to_review")
    return JSONResponse({
        "outcome": outcome, "answer": reply.answer, "reply": reply.reply,
        "evidence": reply.evidence, "evidence_holds": holds, "served_by": reply.served_by,
        "cost_usd": round(actual, 5), "seconds": round(time.time() - started, 1),
    })


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/audit")
def audit_page() -> FileResponse:
    return FileResponse(WEB / "audit.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
