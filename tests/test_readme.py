"""The README quotes the assistant's instructions. This keeps the quotes equal to the code."""

from __future__ import annotations

import re
from pathlib import Path

from catalog_audit import assistant

README = Path(__file__).resolve().parents[1] / "README.md"


def flat(text: str) -> str:
    """Drop blockquote markers and line wrapping."""
    return re.sub(r"\s+", " ", re.sub(r"^> ?", "", text, flags=re.MULTILINE)).strip()


def test_readme_quotes_the_instructions_in_use():
    readme = flat(README.read_text(encoding="utf-8"))
    paragraphs = [p for p in assistant.SYSTEM["C"].split("\n\n") if p.strip()]
    assert len(paragraphs) == 5  # three in the base text, one added by B, one added by C
    for paragraph in paragraphs:
        assert flat(paragraph) in readme, paragraph[:60]
