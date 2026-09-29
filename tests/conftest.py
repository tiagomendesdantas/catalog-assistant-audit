import pytest

from catalog_audit import guard

TEST_MODEL = "test-model"


@pytest.fixture(autouse=True)
def test_price(monkeypatch):
    """A made-up price for a made-up model, so cost paths run without claiming a real price."""
    monkeypatch.setitem(guard.PRICES_PER_MTOK, TEST_MODEL, (2.00, 8.00))


def completion(payload_text: str, finish_reason: str = "stop", refusal: str | None = None,
               prompt_tokens: int = 900, completion_tokens: int = 250) -> dict:
    """A Chat Completions response body, as the API and the Batch API return it."""
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "model": f"{TEST_MODEL}-2026-01-01",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": payload_text, "refusal": refusal}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }
