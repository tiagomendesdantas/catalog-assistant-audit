"""Build the pinned 5,000-product catalog from Open Food Facts.

Source: the official Parquet export on Hugging Face, pinned to one commit so the extract can be
rebuilt byte for byte. Only the columns the demo uses are read, over HTTP range requests; the
7.9 GB file is never downloaded whole.

Population: products sold in the United States (countries_tags contains en:united-states) that have
an English product name and are not marked obsolete. The catalog is a simple random sample of that
population, drawn by sorting on md5(code + seed), so the draw is reproducible and does not depend
on file order.

Output (Open Database License, see data/LICENSE):
    data/catalog/products.jsonl   one product per line, sorted by code
    data/catalog/manifest.json    source revision, population count, seed, SHA-256 of the extract

Usage:  uv run python scripts/build_snapshot.py
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import duckdb

REVISION = "55d0b529729e80e9e4bd1159e64ee755eb108c6b"  # openfoodfacts/product-database, 2026-09-29
SOURCE = (
    "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/"
    f"{REVISION}/food.parquet"
)
SEED = "catalog-assistant-audit-2026-09-29"
SAMPLE_SIZE = 5_000

# Per-100 g nutrients shown to the assistant. Sodium and energy in kJ are left out on purpose:
# each can be converted from a field that is shown, which would blur what "not in the record" means.
NUTRIENTS = ["energy-kcal", "fat", "saturated-fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]

OUT = Path(__file__).resolve().parents[1] / "data" / "catalog"
PLACEHOLDER_TEXT = {"undefined", "null", "none", "n/a"}

ELIGIBLE = """
    list_contains(countries_tags, 'en:united-states')
    AND coalesce(obsolete, false) = false
    AND len(list_filter(product_name, x -> x.lang = 'en' AND trim(x.text) <> '')) > 0
"""


def english(struct_list_sql: str) -> str:
    return f"list_filter({struct_list_sql}, x -> x.lang = 'en' AND trim(x.text) <> '')[1].text"


class _KeepRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def signed_url(url: str) -> str:
    """Resolve the Hugging Face redirect once.

    Every range request against huggingface.co/.../resolve/ counts against its rate limit, and a
    Parquet scan makes thousands of them. The signed storage URL it redirects to serves the same
    bytes without that limit, for long enough to finish the scan.
    """
    opener = urllib.request.build_opener(_KeepRedirect)
    req = urllib.request.Request(url, method="HEAD")
    try:
        opener.open(req, timeout=30)
    except urllib.error.HTTPError as err:
        if err.code in (301, 302, 303, 307, 308) and err.headers.get("Location"):
            return err.headers["Location"]
        raise
    return url


LOCAL = Path(__file__).resolve().parents[1] / "data" / "raw" / "food.parquet"


def main() -> None:
    t0 = time.time()
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false;")
    if LOCAL.exists():
        # A local copy of the pinned file is much faster than thousands of range requests. Its
        # SHA-256 must match the hash Hugging Face publishes for this revision (x-linked-etag).
        source = str(LOCAL)
        print(f"reading local copy {LOCAL} (verify with data/raw/food.parquet.sha256)")
    else:
        source = signed_url(SOURCE)
        con.sql("INSTALL httpfs; LOAD httpfs;")
        con.sql("SET http_retries = 8; SET http_retry_wait_ms = 2000; SET http_retry_backoff = 2;")
        con.sql("SET allow_asterisks_in_http_paths = true;")  # signed URLs carry '*' in their policy

    eligible = [
        row[0] for row in con.sql(f"SELECT code FROM read_parquet('{source}') WHERE {ELIGIBLE}").fetchall()
    ]
    population = len(eligible)
    print(f"eligible products: {population:,}  ({time.time() - t0:.0f}s)")
    codes = sorted(eligible, key=lambda c: hashlib.md5(f"{c}{SEED}".encode()).hexdigest())[:SAMPLE_SIZE]
    print(f"sampled codes: {len(codes):,}")
    con.execute("CREATE TEMP TABLE sample_codes(code VARCHAR)")
    con.executemany("INSERT INTO sample_codes VALUES (?)", [(c,) for c in codes])

    nutrient_list = ", ".join(f"'{n}'" for n in NUTRIENTS)
    rows = con.sql(
        f"""
        SELECT
            p.code,
            {english('p.product_name')} AS product_name,
            nullif(trim(p.brands), '') AS brands,
            nullif(trim(p.quantity), '') AS quantity,
            p.categories_tags,
            {english('p.ingredients_text')} AS ingredients_text,
            p.allergens_tags,
            p.traces_tags,
            p.labels_tags,
            CASE WHEN p.nutriscore_grade IN ('a', 'b', 'c', 'd', 'e') THEN p.nutriscore_grade END
                AS nutriscore_grade,
            p.nova_group,
            list_transform(
                list_filter(p.nutriments, n -> n.name IN ({nutrient_list}) AND n."100g" IS NOT NULL),
                n -> {{'name': n.name, 'per_100g': n."100g", 'unit': n.unit}}
            ) AS nutrition_100g,
            p.data_sources_tags,
            p.last_modified_t
        FROM read_parquet('{source}') p
        JOIN sample_codes s USING (code)
        ORDER BY p.code
        """
    )
    columns = rows.columns
    records = [dict(zip(columns, r)) for r in rows.fetchall()]
    print(f"records: {len(records):,}  ({time.time() - t0:.0f}s)")

    OUT.mkdir(parents=True, exist_ok=True)
    extract = OUT / "products.jsonl"
    placeholders = 0
    with extract.open("w", encoding="utf-8") as fh:
        for rec in records:
            # 180 products in the sample carry the literal string "undefined" as their ingredient
            # list. It is an export artifact, not an ingredient list, so it is stored as missing.
            if (rec["ingredients_text"] or "").strip().lower() in PLACEHOLDER_TEXT:
                rec["ingredients_text"] = None
                placeholders += 1
            rec["nutrition_100g"] = {
                n["name"]: {"value": round(float(n["per_100g"]), 3), "unit": n["unit"]}
                for n in (rec["nutrition_100g"] or [])
            }
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    digest = hashlib.sha256(extract.read_bytes()).hexdigest()
    manifest = {
        "source": "Open Food Facts, openfoodfacts/product-database on Hugging Face (food.parquet)",
        "revision": REVISION,
        "license": "Open Database License (ODbL) 1.0; contents under the Database Contents License",
        "population": "countries_tags contains en:united-states, English product name, not obsolete",
        "population_count": population,
        "sample_size": len(records),
        "sampling": f"simple random sample without replacement: the {SAMPLE_SIZE:,} eligible codes "
                    f"with the smallest md5(code + '{SEED}')",
        "nutrients_per_100g": NUTRIENTS,
        "cleaning": f"ingredient lists equal to {sorted(PLACEHOLDER_TEXT)} stored as missing "
                    f"({placeholders} products)",
        "sha256_products_jsonl": digest,
        "source_sha256": (LOCAL.with_suffix(".parquet.sha256").read_text().split()[0]
                          if LOCAL.with_suffix(".parquet.sha256").exists() else None),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
