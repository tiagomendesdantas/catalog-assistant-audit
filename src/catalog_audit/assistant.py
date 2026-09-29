"""The product assistant under test, in three configurations.

    A  baseline   a helpful store assistant with the product record in context
    B  grounded   A, plus: answer only from the record, otherwise say the catalog does not list it
    C  evidence   B, plus: copy the record fields relied on; a deterministic check then routes any
                  answer whose evidence does not match the record to human review

All three return the same structured output, so grading never depends on reading free text.
The model runs on the OpenAI Chat Completions API with a strict JSON schema.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

# The model is set per deployment and per run; there is deliberately no built-in default.
MODEL = os.getenv("OPENAI_MODEL", "")
EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
MAX_TOKENS = 4_000

_BASE = (
    "You are the shopping assistant of an online grocery store. A customer is asking about one "
    "product, and its catalog record is included with the question. Answer helpfully and briefly.\n\n"
    "Fill the fields as follows. status: \"answered\" if you give an answer, \"cannot_answer\" if "
    "you do not. answer: the short answer only (a number with its unit, a grade letter, a group "
    "number, or yes/no), or an empty string. reply: the sentence the customer will read."
)
_GROUNDED = (
    "\n\nAnswer only from the catalog record. If the record does not contain what the customer "
    "asks about, set status to \"cannot_answer\" and tell the customer the catalog does not list "
    "it. Do not estimate, calculate, or rely on what you know about similar products."
)
_EVIDENCE = (
    "\n\nWhen you answer, list in evidence every record field you relied on, with its value "
    "copied exactly as it appears in the record. Name nested fields with a dot, for example "
    "nutrition_per_100g.sugars."
)

SYSTEM = {"A": _BASE, "B": _BASE + _GROUNDED, "C": _BASE + _GROUNDED + _EVIDENCE}


def schema(config: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "status": {"type": "string", "enum": ["answered", "cannot_answer"]},
        "answer": {"type": "string"},
        "reply": {"type": "string"},
    }
    required = ["status", "answer", "reply"]
    if config == "C":
        properties["evidence"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        }
        required.append("evidence")
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def user_message(record_json: str, question: str) -> str:
    return f"Catalog record:\n```json\n{record_json}\n```\n\nCustomer question: {question}"


def request_params(config: str, record_json: str, question: str, model: str = MODEL,
                   effort: str | None = EFFORT) -> dict[str, Any]:
    """Body of a Chat Completions request. Used as-is for live calls and inside batch lines."""
    if not model:
        raise ValueError("No model set: pass --model or set OPENAI_MODEL.")
    params: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "developer", "content": SYSTEM[config]},
            {"role": "user", "content": user_message(record_json, question)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "catalog_answer", "schema": schema(config), "strict": True},
        },
        "max_completion_tokens": MAX_TOKENS,
    }
    if effort:  # reasoning models only; set OPENAI_REASONING_EFFORT="" for models without it
        params["reasoning_effort"] = effort
    return params


@dataclass(frozen=True)
class Reply:
    status: str | None  # None when the call failed or the output was unusable
    answer: str
    reply: str
    evidence: list[dict[str, str]]
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    served_by: str | None


def parse_message(completion: Any) -> Reply:
    """Turn a Chat Completions response (object or dict) into a Reply. Never raises on bad output.

    Output tokens include reasoning tokens, which are billed as output.
    """
    body = completion if isinstance(completion, dict) else completion.model_dump()
    usage = body.get("usage") or {}
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    stop = "refusal" if message.get("refusal") else choice.get("finish_reason")
    base = {"stop_reason": stop, "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0), "served_by": body.get("model")}
    if stop != "stop":
        return Reply(status=None, answer="", reply="", evidence=[], **base)
    try:
        data = json.loads(message.get("content") or "")
    except json.JSONDecodeError:
        return Reply(status=None, answer="", reply="", evidence=[], **base)
    return Reply(status=data.get("status"), answer=data.get("answer", ""), reply=data.get("reply", ""),
                 evidence=data.get("evidence", []), **base)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _lookup(record: dict[str, Any], field: str) -> Any:
    node: Any = record
    for part in field.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def evidence_holds(record: dict[str, Any], reply: Reply, family: str | None = None) -> bool:
    """True when every cited field exists and its quoted value appears in the record.

    Only answered replies are checked; a "cannot_answer" has nothing to verify. For nutrition the
    number in the answer must also be one of the quoted numbers, so the model cannot quote one field
    and answer with another.
    """
    if reply.status != "answered":
        return True
    if not reply.evidence:
        return False
    quoted_numbers: set[float] = set()
    for item in reply.evidence:
        value = _lookup(record, item.get("field", ""))
        if value is None:
            return False
        quoted = _norm(item.get("value", ""))
        if not quoted:
            return False
        haystack = _norm(", ".join(map(str, value)) if isinstance(value, list) else value)
        if quoted not in haystack:
            return False
        quoted_numbers.update(float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", quoted))
    if family == "nutrition":
        m = re.search(r"-?\d+(?:[.,]\d+)?", reply.answer or "")
        if not m or float(m.group().replace(",", ".")) not in quoted_numbers:
            return False
    return True
