# Catalog assistant audit

How often does a grocery product assistant answer a question its catalog record cannot answer?
This project measures it on 5,000 real products, for three versions of the same assistant, and
serves the grounded version as a demo that shows its evidence.

**Live demo:** _added at deployment_ · **Results:** [`/audit`](#results)

## The problem

Online grocers are putting assistants on top of their product catalogs, and the catalogs have
gaps: a nutrition value never entered, an empty allergen list. A shopper asking "does this contain
milk?" about a product whose record says nothing should hear that the catalog doesn't list it. An
assistant that fills the gap from general knowledge will often sound right and sometimes be wrong,
on exactly the questions where being wrong matters.

Teams building these assistants tend to ask for the same two things: answers that point to their
source, and a way to send uncertain questions to a person. This project builds both and measures
what they change.

## What it does

- **Demo.** Pick one of 5,000 US products from Open Food Facts, see the record exactly as the
  assistant sees it, and ask a question. The answer comes back with the record fields it relied on.
  A deterministic check compares the cited values with the record and sends mismatches to human
  review instead of to the shopper.
- **Audit.** Three configurations answer the same questions, sampled so every question has a known
  right answer taken from the record, including "the record doesn't say":
  - **A · Baseline:** a helpful store assistant with the record in context.
  - **B · Grounded:** A, plus the instruction to answer only from the record.
  - **C · Grounded + evidence:** B, plus copying the record fields it relied on; reported with and
    without the evidence check.

## Results

_Written from the test run._

## How the numbers are produced

- **Catalog.** A simple random sample of 5,000 products sold in the US, from a pinned revision of
  the official Open Food Facts export ([`DATA.md`](DATA.md)).
- **Questions.** Every product-attribute pair falls into one of seven strata: a nutrient value in
  the record or not, a Nutri-Score/NOVA value in the record or not, an allergen declared, not
  declared while others are, or no allergen information at all. Pairs whose answer the record can't
  settle (an empty allergen list next to an ingredient list) are excluded by rule. Within each
  stratum, products are drawn at random and one attribute asked per product.
- **Grading.** Deterministic, against the record. No model grades another model.
- **Estimation.** Each question carries the inverse of its inclusion probability. Rates use the
  Hájek estimator with a linearised variance; configurations are compared question by question.
  The interval code has a coverage test.
- **Discipline.** Products were split into development and test before any question was drawn.
  Prompts were tuned on development questions only; every test run is logged in
  `data/runs/log.jsonl`. The plan was committed before the first model call
  ([`docs/EVAL_PLAN.md`](docs/EVAL_PLAN.md)).

## Run it

```bash
uv sync
uv run pytest                                   # grading, estimation, app
uv run uvicorn catalog_audit.app:app --reload   # demo at http://127.0.0.1:8000

# Rebuild the data from the pinned source
uv run python scripts/build_snapshot.py
uv run python -m catalog_audit.questions

# Evaluate (needs OPENAI_API_KEY)
uv run python scripts/run_eval.py --split dev --model <model> --dry-run
uv run python scripts/run_eval.py --split dev --model <model>
uv run python scripts/score.py <run_id>
```

Live questions in the demo need `OPENAI_API_KEY` and `OPENAI_MODEL`, and the model must have a
verified price in `src/catalog_audit/guard.py`; otherwise live questions stay off, because the
spend limits could not be enforced. They are limited per visitor and by a daily budget
(`LIVE_PER_IP_PER_HOUR`, `LIVE_PER_IP_PER_DAY`, `LIVE_DAILY_USD`); everything else on the site is
precomputed.

## Data and licence

Contains data from [Open Food Facts](https://openfoodfacts.org), available under the
[Open Database License](https://opendatacommons.org/licenses/odbl/1-0/). The data in `data/` is
released under the ODbL ([`data/LICENSE`](data/LICENSE)); the code is MIT ([`LICENSE`](LICENSE)).
This is not food-safety or allergy advice: the catalog is crowdsourced and, in its own words,
"can contain errors and must not be used for medical purposes."

## About

A dated portfolio project by Tiago Dantas, built in September 2026 on public data. It is not
client work and has not been used in production.
