"""The question bank: which product-attribute pairs are asked, and with what weight.

Every pair in the catalog falls into one stratum:

    nutrition_present   the per-100 g value is in the record          -> expected: the value
    nutrition_missing   the per-100 g value is not in the record      -> expected: cannot answer
    score_present       Nutri-Score grade or NOVA group is present    -> expected: the grade/group
    score_missing       it is not                                     -> expected: cannot answer
    allergen_yes        the allergen is declared                      -> expected: yes
    allergen_no         other allergens are declared, this one is not,
                        it is not in traces, and no ingredient word
                        points to it                                  -> expected: no
    allergen_missing    no allergens, no traces and no ingredients    -> expected: cannot answer

Pairs that fit none of these (for example, an empty allergen list next to an ingredient list)
are left out on purpose: the right answer would depend on reading the ingredients, and the
catalog does not settle it. Nutrient values outside physical bounds (more than 900 kcal or
100 g per 100 g) are catalog errors; they stay in the record but are never asked about.

Sampling, within each stratum: draw products at random without replacement, then one eligible
attribute of each drawn product at random. At most one question per product per stratum, so
questions are independent units. The inclusion probability of a pair is
(n_h / M_h) * (1 / k_p), where M_h is the number of products with at least one eligible pair in
the stratum and k_p the number of eligible pairs of product p. Each question carries 1/pi.

Products are split into development (prompt tuning) and test (reported numbers) by a hash of the
product code, before any question is drawn.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from catalog_audit.catalog import NUTRIENT_LABELS, english_tags, load, plausible

SEED = "catalog-assistant-audit-questions-2026-09-29"
DEV_SHARE = 0.20
PER_STRATUM = {"dev": 30, "test": 120}

# Major US food allergens (FALCPA + sesame), mapped to the Open Food Facts tag and to ingredient
# words that make a "no" ambiguous. The word lists are deliberately broad: a false match only
# removes a pair from the "no" stratum, it never mislabels one.
ALLERGENS = {
    "milk": ("en:milk", ["milk", "whey", "casein", "butter", "cream", "cheese", "yogurt", "yoghurt",
                         "lactose", "ghee", "curd", "dairy"]),
    "eggs": ("en:eggs", ["egg", "albumin", "mayonnaise", "meringue"]),
    "fish": ("en:fish", ["fish", "anchov", "salmon", "tuna", "cod", "sardine", "tilapia", "pollock",
                         "trout", "mackerel"]),
    "shellfish": ("en:crustaceans", ["shrimp", "prawn", "crab", "lobster", "crayfish", "krill",
                                      "shellfish"]),
    "tree nuts": ("en:nuts", ["almond", "cashew", "walnut", "pecan", "hazelnut", "pistachio",
                              "macadamia", "brazil nut", "pine nut", "coconut", "nut"]),
    "peanuts": ("en:peanuts", ["peanut", "groundnut", "arachis"]),
    "gluten": ("en:gluten", ["wheat", "gluten", "barley", "rye", "spelt", "semolina", "durum",
                             "malt", "flour", "oat"]),
    "soy": ("en:soybeans", ["soy", "soya", "edamame", "tofu", "lecithin", "miso", "tempeh"]),
    "sesame": ("en:sesame-seeds", ["sesame", "tahini"]),
}

NUTRITION_TEMPLATES = [
    "How much {what} does {name} have per 100 g?",
    "What's the {what} content of {name}, per 100 grams?",
]
SCORE_TEMPLATES = {
    "nutri_score_grade": [
        "What is the Nutri-Score grade of {name}?",
        "Which Nutri-Score does {name} have?",
    ],
    "nova_group": [
        "What NOVA group is {name} in?",
        "Which NOVA processing group does {name} belong to?",
    ],
}
ALLERGEN_TEMPLATES = [
    "Does {name} contain {what}?",
    "Does {name} have {what} in it?",
]


@dataclass(frozen=True)
class Pair:
    code: str
    stratum: str
    family: str  # nutrition | score | allergen
    attribute: str  # nutrient key, score field, or allergen name
    expected: str  # the value, "yes"/"no", or "CANNOT_ANSWER"


@dataclass(frozen=True)
class Question:
    qid: str
    split: str
    code: str
    stratum: str
    family: str
    attribute: str
    expected: str
    text: str
    weight: float  # 1 / inclusion probability
    stratum_products: int  # M_h in this split
    stratum_pairs: int  # N_h in this split


def split_of(code: str) -> str:
    h = int(hashlib.md5(f"{code}|{SEED}|split".encode()).hexdigest(), 16)
    return "dev" if (h % 10_000) / 10_000 < DEV_SHARE else "test"


def _mentions(text: str, words: list[str]) -> bool:
    text = text.lower()
    return any(w in text for w in words)


def pairs_for(product: dict[str, Any]) -> list[Pair]:
    code = product["code"]
    out: list[Pair] = []
    nutrition = product.get("nutrition_100g") or {}
    for key in NUTRIENT_LABELS:
        if key in nutrition:
            value = nutrition[key]["value"]
            if plausible(key, value):  # impossible values are catalog errors; never asked about
                out.append(Pair(code, "nutrition_present", "nutrition", key, f"{value:g}"))
        else:
            out.append(Pair(code, "nutrition_missing", "nutrition", key, "CANNOT_ANSWER"))

    grade = product.get("nutriscore_grade")
    out.append(Pair(code, "score_present" if grade else "score_missing", "score",
                    "nutri_score_grade", grade.upper() if grade else "CANNOT_ANSWER"))
    nova = product.get("nova_group")
    out.append(Pair(code, "score_present" if nova is not None else "score_missing", "score",
                    "nova_group", str(int(nova)) if nova is not None else "CANNOT_ANSWER"))

    declared = set(english_tags(product.get("allergens_tags")))
    traces = set(english_tags(product.get("traces_tags")))
    any_allergen_info = bool(product.get("allergens_tags")) or bool(product.get("traces_tags"))
    ingredients = product.get("ingredients_text") or ""
    context = f"{ingredients} {product.get('product_name', '')}"
    for name, (tag, words) in ALLERGENS.items():
        if tag in declared:
            out.append(Pair(code, "allergen_yes", "allergen", name, "yes"))
        elif declared and tag not in traces and not _mentions(context, words):
            out.append(Pair(code, "allergen_no", "allergen", name, "no"))
        elif not any_allergen_info and not ingredients.strip():
            out.append(Pair(code, "allergen_missing", "allergen", name, "CANNOT_ANSWER"))
    return out


def question_text(pair: Pair, name: str, rng: random.Random) -> str:
    if pair.family == "nutrition":
        what = NUTRIENT_LABELS[pair.attribute]
        what = "energy (calories)" if what == "energy" else what
        return rng.choice(NUTRITION_TEMPLATES).format(what=what, name=name)
    if pair.family == "score":
        return rng.choice(SCORE_TEMPLATES[pair.attribute]).format(name=name)
    return rng.choice(ALLERGEN_TEMPLATES).format(what=pair.attribute, name=name)


def build(products: dict[str, dict[str, Any]]) -> tuple[list[Question], dict[str, Any]]:
    by_stratum: dict[tuple[str, str], dict[str, list[Pair]]] = defaultdict(lambda: defaultdict(list))
    for code, product in products.items():
        for pair in pairs_for(product):
            by_stratum[(split_of(code), pair.stratum)][code].append(pair)

    rng = random.Random(SEED)
    questions: list[Question] = []
    frame: dict[str, Any] = {}
    for (split, stratum) in sorted(by_stratum):
        per_product = by_stratum[(split, stratum)]
        codes = sorted(per_product)
        m_h = len(codes)
        n_pairs = sum(len(v) for v in per_product.values())
        n_h = min(PER_STRATUM[split], m_h)
        drawn = rng.sample(codes, n_h)
        frame[f"{split}/{stratum}"] = {"products": m_h, "pairs": n_pairs, "sampled": n_h}
        for i, code in enumerate(sorted(drawn)):
            options = sorted(per_product[code], key=lambda p: p.attribute)
            pair = rng.choice(options)
            weight = (m_h / n_h) * len(options)
            text = question_text(pair, products[code]["product_name"], rng)
            questions.append(Question(
                qid=f"{split}-{stratum}-{i:03d}", split=split, code=code, stratum=stratum,
                family=pair.family, attribute=pair.attribute, expected=pair.expected, text=text,
                weight=weight, stratum_products=m_h, stratum_pairs=n_pairs,
            ))
    return questions, frame


def write(questions: list[Question], frame: dict[str, Any], out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "questions.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(asdict(q), ensure_ascii=False, sort_keys=True) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"seed": SEED, "dev_share": DEV_SHARE, "per_stratum": PER_STRATUM,
                "frame": frame, "sha256_questions_jsonl": digest}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return digest


def read(path: Path) -> list[Question]:
    with path.open(encoding="utf-8") as fh:
        return [Question(**json.loads(line)) for line in fh]


if __name__ == "__main__":
    from catalog_audit.catalog import DATA

    qs, fr = build(load())
    digest = write(qs, fr, DATA / "questions")
    print(json.dumps(fr, indent=2))
    print(f"{len(qs)} questions · sha256 {digest}")
