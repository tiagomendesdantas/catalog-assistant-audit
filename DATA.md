# Data sources and licences

Checked on 2026-09-29. Each entry quotes the governing sentence from the source.

## Open Food Facts — product catalog

- **What:** the official Parquet export, `food.parquet`, in the Hugging Face dataset
  [`openfoodfacts/product-database`](https://huggingface.co/datasets/openfoodfacts/product-database),
  pinned to revision `55d0b529729e80e9e4bd1159e64ee755eb108c6b` (2026-09-29, 4,762,888 products).
  The nightly exports on static.openfoodfacts.org are overwritten each night and cannot be pinned;
  the Hugging Face revision can.
- **Licence:** "The Open Food Facts database is available under the Open Database License.
  Individual contents of the database are available under the Database Contents License. Products
  images are available under the Creative Commons Attribution ShareAlike licence."
  ([terms of use](https://world.openfoodfacts.org/terms-of-use))
- **Commercial use:** "The licences are free licences that authorize the use and reproduction of
  the content for all purposes, including commercial use, under certain conditions" (same page).
- **Attribution requested:** "Contains data from Open Food Facts, available under the Open Database
  License" ([data page](https://world.openfoodfacts.org/data)). It appears in the app footer, in this
  repository's README and in [`data/LICENSE`](data/LICENSE); each product in the app links back to
  its Open Food Facts page.
- **Data quality, in the source's own words:** "It can contain errors due for instance to
  inaccurate information on labels and packaging, manual input of data, or processing of data."
  and "The information and data is provided only for indicative information. It can contain errors
  and must not be used for medical purposes." This is why the app states that it is not
  food-safety or allergy advice.

### What this repository does with it

- `scripts/build_snapshot.py` reads the pinned file over HTTP range requests (only the columns it
  needs), keeps products sold in the United States that have an English name and are not obsolete,
  and draws 5,000 of them at random (sorted by `md5(code + seed)`, so the draw is reproducible).
- Product images are not used.
- The extract (`data/catalog/`) and everything derived from it in `data/` is a Derivative Database
  under ODbL section 4.4 and is released under the ODbL (see [`data/LICENSE`](data/LICENSE)). The
  pages and aggregate results the app shows are Produced Works (ODbL section 4.3) and carry the
  attribution notice. The code is MIT.

## Model

The assistant runs on an OpenAI model through the Chat Completions API, with a strict JSON schema
for its output. Model, reasoning effort and date of every evaluation run are recorded in
`data/runs/log.jsonl`.
