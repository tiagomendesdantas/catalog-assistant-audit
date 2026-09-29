# Evaluation plan

Written and committed before the first model call. The commit that adds the question bank also
records its SHA-256 in `data/questions/manifest.json`; any later change to the questions would
change that hash.

## Question

When a product assistant answers from a grocery catalog record, how often does it answer a
question the record cannot answer, and how much does grounding and an evidence check change that
without costing accuracy on questions the record can answer?

## Units and population

- Catalog: 5,000 US products from Open Food Facts (see `DATA.md`).
- A question is a product-attribute pair. Every pair belongs to one of seven strata, defined in
  `src/catalog_audit/questions.py`. Pairs whose right answer the record cannot settle are excluded
  by rule, not by inspection.
- Products are split 20/80 into development and test by a hash of the product code, before any
  question is drawn.

## Configurations

- **A · Baseline:** a helpful store assistant with the record in context.
- **B · Grounded:** A plus the instruction to answer only from the record.
- **C · Grounded + evidence:** B plus copying the record fields relied on.
- **C + evidence check:** C, with a deterministic check that routes an answer to human review when
  its cited fields or values are not in the record.

Same model, effort setting and output schema family for all. Only the system prompt and, for C,
the evidence field differ.

## Outcomes and metrics (primary)

1. **Unsupported-answer rate:** among questions the record cannot answer, the share answered.
2. **Accuracy when answerable:** among questions the record answers, the share answered correctly.
   Declining, a wrong value and review routing count as not correct.

Secondary: abstention when answerable, review-routing rate, what routed answers would have been,
cost per 1,000 questions, failures (refusal, malformed output, API error), each reported, never
dropped.

## Estimation

Hájek estimator within stratum with weights 1/π, linearised variance, strata combined by eligible
pair counts; paired differences against A on the same questions. 95% intervals. Details in
`src/catalog_audit/estimate.py`, with a coverage test in `tests/`.

## Rules for the test split

- Prompts are adjusted only on development questions.
- Every test run is logged in `data/runs/log.jsonl` and the README reports how many there were.
- If a configuration loses to the baseline, that is the result and it is published as such.
