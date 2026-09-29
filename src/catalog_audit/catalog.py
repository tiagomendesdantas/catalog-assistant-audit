"""Load the pinned catalog and render a product the way the assistant sees it.

The rendered record is the only information the assistant gets. Fields that are empty in the
catalog are left out, as a product API that omits nulls would do. "Not in the record" in the
evaluation means exactly this: the key is absent from the JSON below.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[2] / "data"
CATALOG = DATA / "catalog" / "products.jsonl"

NUTRIENT_LABELS = {
    "energy-kcal": "energy",
    "fat": "fat",
    "saturated-fat": "saturated fat",
    "carbohydrates": "carbohydrates",
    "sugars": "sugars",
    "fiber": "fiber",
    "proteins": "protein",
    "salt": "salt",
}

# Open Food Facts stores every per-100 g value in one unit: kcal for energy, grams for the rest.
# Its `unit` field is the unit a contributor typed the value in, not the unit of the stored value,
# so it must not be shown next to the per-100 g number.
CANONICAL_UNIT = {"energy-kcal": "kcal"}

# Physical bounds per 100 g. Values outside them are catalog errors: shown to the assistant as
# they are, but never asked about, so a model that doubts an impossible number is not graded wrong.
PLAUSIBLE_MAX = {"energy-kcal": 900.0}
DEFAULT_MAX_G = 100.0


def unit_of(nutrient: str) -> str:
    return CANONICAL_UNIT.get(nutrient, "g")


def plausible(nutrient: str, value: float) -> bool:
    return 0.0 <= value <= PLAUSIBLE_MAX.get(nutrient, DEFAULT_MAX_G)


ALLERGEN_NAMES = {
    "en:milk": "milk",
    "en:eggs": "eggs",
    "en:fish": "fish",
    "en:crustaceans": "crustaceans",
    "en:nuts": "tree nuts",
    "en:peanuts": "peanuts",
    "en:gluten": "gluten",
    "en:soybeans": "soybeans",
    "en:sesame-seeds": "sesame seeds",
    "en:celery": "celery",
    "en:mustard": "mustard",
    "en:lupin": "lupin",
    "en:molluscs": "molluscs",
    "en:sulphur-dioxide-and-sulphites": "sulphites",
}


def _tag_label(tag: str) -> str:
    return tag.split(":", 1)[-1].replace("-", " ")


def english_tags(tags: list[str] | None) -> list[str]:
    return [t for t in (tags or []) if t.startswith("en:")]


def format_number(value: float) -> str:
    return f"{value:g}"


def render(product: dict[str, Any]) -> dict[str, Any]:
    """The product record exactly as the assistant receives it."""
    out: dict[str, Any] = {"product_name": product["product_name"]}
    if product.get("brands"):
        out["brand"] = product["brands"]
    if product.get("quantity"):
        out["package_size"] = product["quantity"]
    categories = english_tags(product.get("categories_tags"))
    if categories:
        out["categories"] = [_tag_label(t) for t in categories[-3:]]
    if product.get("ingredients_text"):
        out["ingredients"] = product["ingredients_text"]
    allergens = english_tags(product.get("allergens_tags"))
    if allergens:
        out["allergens_declared"] = [ALLERGEN_NAMES.get(t, _tag_label(t)) for t in allergens]
    traces = english_tags(product.get("traces_tags"))
    if traces:
        out["may_contain_traces_of"] = [ALLERGEN_NAMES.get(t, _tag_label(t)) for t in traces]
    labels = english_tags(product.get("labels_tags"))
    if labels:
        out["labels"] = [_tag_label(t) for t in labels[:8]]
    if product.get("nutriscore_grade"):
        out["nutri_score_grade"] = product["nutriscore_grade"].upper()
    if product.get("nova_group") is not None:
        out["nova_group"] = int(product["nova_group"])
    nutrition = product.get("nutrition_100g") or {}
    if nutrition:
        out["nutrition_per_100g"] = {
            NUTRIENT_LABELS[name]: f"{format_number(nutrition[name]['value'])} {unit_of(name)}"
            for name in NUTRIENT_LABELS
            if name in nutrition
        }
    return out


def render_json(product: dict[str, Any]) -> str:
    return json.dumps(render(product), ensure_ascii=False, indent=1)


def render_context(codes: tuple[str, ...] | list[str], products: dict[str, dict[str, Any]]) -> str:
    """One code: that record as a JSON object. Several: the search results as a JSON array."""
    if len(codes) == 1:
        return render_json(products[codes[0]])
    return json.dumps([render(products[c]) for c in codes], ensure_ascii=False, indent=1)


@lru_cache(maxsize=1)
def load(path: Path = CATALOG) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        products = [json.loads(line) for line in fh]
    return {p["code"]: p for p in products}
