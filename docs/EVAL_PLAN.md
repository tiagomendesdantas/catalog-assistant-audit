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

## Models

gpt-6.1-sol (the demo's assistant) and gpt-6-luna (a cheaper comparison), both at
`reasoning_effort="low"`, through the Chat Completions and Batch APIs. Prices in
`src/catalog_audit/guard.py`, from the provider's pricing page on 2026-09-29.

## Changes made on development questions

Recorded here so the reader can see what was tuned before the test run.

- **Round 0 (live smoke test, 7 development questions per model).**
  - The evidence check rejected a correct quote because the model copied a list field as JSON
    (`["eggs", "milk", "soybeans"]`) rather than comma-separated. The check now accepts a list, or
    any subset of its items, in either form. A checker bug, not a model error.
  - With the grounded prompt, "fish is not in the declared allergen list" was read as "the record
    does not say". A sentence defining undeclared allergens was added to the base prompt, so all
    three configurations receive it and the comparison stays like for like.

- **Round 1 (210 development questions, both models).**
  - Two labelling errors, caught because the models' answers were right: a missing part is known
    when its whole is 0 g (no fat means no saturated fat), and a product name that names the
    allergen ("Salted Peanuts") settles the question. Both pair types are now excluded.
  - With the exact record in context, gpt-6.1-sol answered 120/120 answerable questions correctly
    in every configuration and invented 1–3 answers out of 90. gpt-6-luna invented 2–4 out of 90;
    the grounding rule made it decline 8–9 of 30 answerable "not declared" allergen questions.

- **Design change after round 1 (decided by Tiago Dantas, before any test run).** With a clean
  record, both models are near ceiling, which says little about deployed assistants: those receive
  whatever the product search returns. Every question is now also asked in a **retrieval**
  condition: the target record plus the two products whose names are most similar (character
  3–4-gram TF-IDF, cosine; identical names skipped), in a shuffled order. Ground truth is unchanged.
  Wrong or unsupported answers that equal another product's value are counted separately. The
  question bank was regenerated and frozen again; the development/test split is unchanged, and the
  test split has not been used.

## Rules for the test split

- Prompts are adjusted only on development questions.
- Every test run is logged in `data/runs/log.jsonl` and the README reports how many there were.
- If a configuration loses to the baseline, that is the result and it is published as such.
