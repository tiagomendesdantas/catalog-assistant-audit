# Catalog assistant audit

**LLM evaluation · RAG grounding and citation checks · deployed on Railway**

[![ci](https://github.com/tiagomendesdantas/catalog-assistant-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/tiagomendesdantas/catalog-assistant-audit/actions/workflows/ci.yml)

How often does a grocery product assistant answer a question its catalog record cannot answer?
This project measures it on 5,000 real products, for three versions of the same assistant, and
serves the grounded version as a demo that shows its evidence.

**Live demo:** [web-production-78cffc.up.railway.app](https://web-production-78cffc.up.railway.app) ·
**Results page:** [/audit](https://web-production-78cffc.up.railway.app/audit)

## What this project covers

| Area | What is in the repo | Where to look |
|---|---|---|
| **LLM evaluation** | Two OpenAI models and three prompt configurations, compared on 1,680 test questions per model. The right answers come from the catalog, grading is deterministic, and every rate has a 95% interval. Prompts were tuned on development questions only, and the test split was run once per model. | [`docs/EVAL_PLAN.md`](docs/EVAL_PLAN.md), [`questions.py`](src/catalog_audit/questions.py), [`grading.py`](src/catalog_audit/grading.py), [`estimate.py`](src/catalog_audit/estimate.py) |
| **RAG** | The answering half of a retrieval-augmented system. The assistant answers only from the records in its context and cites the fields it used, and a check compares each citation with the record. Every question is also asked with two lookalike products in context, the way a search step returns them. Retrieval quality is not measured: the right record is always in context. | [`assistant.py`](src/catalog_audit/assistant.py), [`questions.py`](src/catalog_audit/questions.py) |
| **Deployment** | A FastAPI service in Docker, running on Railway. CI runs lint, tests, the image build and a secret scan. Live model calls are limited per visitor and by a daily budget. | [`app.py`](src/catalog_audit/app.py), [`guard.py`](src/catalog_audit/guard.py), [`Dockerfile`](Dockerfile), [`ci.yml`](.github/workflows/ci.yml) |

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

Test split: 840 questions per model and condition, 360 of them about something the record does
not list. Two OpenAI models, `reasoning_effort="low"`, run on 2026-09-29. Rates in percent with
95% intervals. "Invented" is the share of unanswerable questions that got an answer anyway;
"correct" is the share of answerable questions answered correctly. Every question was asked twice:
with the exact record, and with the record plus the two products whose names are most similar.

**gpt-6.1-sol**

| Configuration | Invented, exact record | Invented, similar products | Correct, exact record | Correct, similar products |
|---|---:|---:|---:|---:|
| A · baseline | 0.3% (0.0–2.5) | 0.3% (0.0–2.5) | 100.0% (97.8–100.0) | 100.0% (97.8–100.0) |
| B · grounded | 0.0% (0.0–2.3) | 0.0% (0.0–2.3) | 100.0% (97.8–100.0) | 100.0% (97.8–100.0) |
| C · grounded + evidence | 0.0% (0.0–2.3) | 0.0% (0.0–2.3) | 100.0% (97.8–100.0) | 100.0% (97.8–100.0) |
| C + evidence check | 0.0% (0.0–2.3) | 0.0% (0.0–2.3) | 100.0% (97.8–100.0) | 100.0% (97.8–100.0) |

**gpt-6-luna**

| Configuration | Invented, exact record | Invented, similar products | Correct, exact record | Correct, similar products |
|---|---:|---:|---:|---:|
| A · baseline | 1.7% (0.0–3.5) | 0.8% (0.0–3.0) | 99.3% (97.0–100.0) | 98.6% (97.2–100.0) |
| B · grounded | 0.0% (0.0–2.3) | 0.0% (0.0–2.3) | 95.6% (94.1–97.2) | 94.5% (92.6–96.5) |
| C · grounded + evidence | 0.0% (0.0–2.3) | 0.6% (0.0–2.8) | 94.0% (92.0–96.0) | 93.3% (90.8–95.8) |
| C + evidence check | 0.0% (0.0–2.3) | 0.0% (0.0–2.3) | 94.0% (92.0–96.0) | 93.3% (90.8–95.8) |

What the numbers say, for this catalog and these question types:

- **The larger model rarely invents, and lookalike products did not confuse it.** gpt-6.1-sol
  invented one answer in 360 at baseline ("3.2 g of carbohydrates" for a product with no nutrition
  data) and none once told to answer only from the record. The two similar products in context
  changed nothing, and the guardrails cost it no accuracy.
- **On the smaller model, the grounding rule trades invented answers for refused ones.**
  gpt-6-luna, at a twentieth of the price per token, invented in 0.8–1.7% of cases at baseline. The
  grounding rule removed that, but lowered accuracy by 3.6 to 5.3 points (paired intervals exclude
  zero). Nearly all of the loss is one pattern: asked whether a product contains an allergen that is
  absent from a declared allergen list, B and C said the catalog does not list it in 26 and 34 of
  120 questions, against 4 for the baseline.
- **With similar products in context, the smaller model sometimes answered about the wrong
  product.** Four baseline answers and four evidence-configuration answers matched another product's
  record. Asked about the calories in "Oreo", it answered with the 483 kcal of "Oreo Cream Biscuit".
- **The evidence check caught those, and only those.** It sent 4 of configuration C's answers to
  review. All 4 were answers the record could not support, each taken from a neighbouring product;
  no correct answer was stopped.

Cost per 1,000 questions at standard prices: gpt-6.1-sol $1.20–1.60 with the exact record and
$1.89–2.29 with similar products; gpt-6-luna $0.06–0.12. Every test and development run is logged
in `data/runs/log.jsonl`; the test split was run once per model. The gpt-6-luna run was interrupted
by an account billing error after 3,802 of 5,040 requests; the 1,238 requests that never got a
response were re-sent unchanged and merged, and that is logged too.

### Limitations

- Ground truth is the catalog record, not the physical product. An answer that is true of the real
  product counts as invented if the record does not state it.
- "Similar products" are the nearest names in this 5,000-product sample, not the output of a
  production search engine, which may return closer or looser matches.
- Questions follow fixed English templates; real customers phrase things more loosely.
- Allergen questions leave out cases the record cannot settle, such as an empty allergen list next to
  an ingredient list. Those are common and deserve their own study.
- Two models, one date, one sample of one catalog. The rates describe these configurations here, not
  product assistants in general.

## How the numbers are produced

- **Catalog.** A simple random sample of 5,000 products sold in the US, from a pinned revision of
  the official Open Food Facts export ([`DATA.md`](DATA.md)).
- **Questions.** Every product-attribute pair falls into one of seven strata: a nutrient value in
  the record or not, a Nutri-Score/NOVA value in the record or not, an allergen declared, not
  declared while others are, or no allergen information at all. Pairs whose answer the record can't
  settle (an empty allergen list next to an ingredient list) are excluded by rule. Within each
  stratum, products are drawn at random and one attribute asked per product.
- **Context.** Each question is asked with the exact record, and again with the record plus the two
  products whose names are closest (character 3–4-gram TF-IDF, cosine, identical names skipped), in
  a shuffled order. Ground truth is always the named product's record.
- **Grading.** Deterministic, against the record. No model grades another model.
- **Estimation.** Each question carries the inverse of its inclusion probability. Rates use the
  Hájek estimator with a linearised variance; configurations and conditions are compared question by
  question. A stratum whose sampled outcomes are all identical contributes the variance implied by
  its Wilson interval rather than zero, so a rare event is never reported as precisely measured. The
  interval code has a coverage test.
- **Discipline.** Products were split into development and test before any question was drawn.
  Prompts and grading rules were changed on development questions only, and every change is listed
  with its reason in [`docs/EVAL_PLAN.md`](docs/EVAL_PLAN.md), which was committed before the first
  model call. Every run is logged in `data/runs/log.jsonl`.

## Run it

```bash
uv sync
uv run pytest                                   # grading, estimation, app
uv run uvicorn catalog_audit.app:app --reload   # demo at http://127.0.0.1:8000

# Rebuild the data from the pinned source
uv run python scripts/build_snapshot.py
uv run python -m catalog_audit.questions

# Evaluate (needs OPENAI_API_KEY, in the environment or a git-ignored .env)
uv run python scripts/run_eval.py --split dev --model gpt-6-luna --dry-run
uv run python scripts/run_eval.py --split dev --model gpt-6-luna            # Batch API
uv run python scripts/run_eval.py --split dev --model gpt-6.1-sol --mode flex  # the Batch API refused this model
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
