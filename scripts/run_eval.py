"""Run the assistant configurations over one split of the question bank, through the OpenAI Batch API.

    uv run python scripts/run_eval.py --split dev --model <model> --dry-run   # counts and cost
    uv run python scripts/run_eval.py --split dev --model <model>             # tune prompts here
    uv run python scripts/run_eval.py --split test --model <model> --confirm-test

Every run is appended to data/runs/log.jsonl, including test runs, so the README can say how many
times the test set was used. Raw responses are kept in data/runs/<run_id>/raw.jsonl.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog_audit.assistant import EFFORT, MAX_TOKENS, MODEL, request_params
from catalog_audit.catalog import DATA, load, render_json
from catalog_audit.guard import PRICES_PER_MTOK
from catalog_audit.questions import read

RUNS = DATA / "runs"
ENDPOINT = "/v1/chat/completions"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from a local, git-ignored .env; never overrides the environment."""
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
BATCH_DISCOUNT = 0.5  # Batch API price relative to standard; confirm on the pricing page per model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--configs", default="A,B,C")
    ap.add_argument("--model", default=MODEL, required=not MODEL)
    ap.add_argument("--effort", default=EFFORT, help='reasoning effort; "" for non-reasoning models')
    ap.add_argument("--limit", type=int, default=0, help="first N questions only (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm-test", action="store_true")
    args = ap.parse_args()
    if args.split == "test" and not (args.confirm_test or args.dry_run):
        sys.exit("Test runs are counted in the README. Re-run with --confirm-test.")

    qpath = DATA / "questions" / "questions.jsonl"
    questions = [q for q in read(qpath) if q.split == args.split]
    if args.limit:
        questions = questions[: args.limit]
    catalog = load()
    configs = args.configs.split(",")
    requests = [
        (f"{c}-{q.qid}", request_params(c, render_json(catalog[q.code]), q.text, args.model, args.effort))
        for c in configs
        for q in questions
    ]

    chars = sum(len(m["content"]) for _, p in requests for m in p["messages"])
    est_in = chars / 3.5 + 300 * len(requests)  # schema and framing overhead
    est_out = 400 * len(requests)  # low-effort reasoning plus a short JSON answer
    line = f"{len(requests)} requests · {len(questions)} questions × {len(configs)} configs · {args.model}"
    if args.model in PRICES_PER_MTOK:
        price_in, price_out = PRICES_PER_MTOK[args.model]
        est = (est_in * price_in + est_out * price_out) / 1_000_000 * BATCH_DISCOUNT
        worst = (est_in * price_in + MAX_TOKENS * len(requests) * price_out) / 1_000_000 * BATCH_DISCOUNT
        line += f" · estimated ${est:.2f} (worst case ${worst:.2f}) at batch prices"
    else:
        line += f" · ~{est_in / 1e6:.2f}M input and ~{est_out / 1e6:.2f}M output tokens (price not verified)"
    print(line)
    if args.dry_run:
        return

    import openai

    load_dotenv()
    client = openai.OpenAI()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = "".join(
        json.dumps({"custom_id": cid, "method": "POST", "url": ENDPOINT, "body": body}) + "\n"
        for cid, body in requests
    )
    upload = client.files.create(file=("batch.jsonl", io.BytesIO(lines.encode())), purpose="batch")
    batch = client.batches.create(input_file_id=upload.id, endpoint=ENDPOINT, completion_window="24h",
                                  metadata={"project": "catalog-assistant-audit", "split": args.split})
    print(f"batch {batch.id} submitted")
    while batch.status not in ("completed", "failed", "expired", "cancelled"):
        time.sleep(30)
        batch = client.batches.retrieve(batch.id)
        counts = batch.request_counts
        print(f"  {batch.status} · completed {counts.completed}/{counts.total} · failed {counts.failed}")
    if batch.status != "completed":
        sys.exit(f"batch ended as {batch.status}: {batch.errors}")

    run_id = f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{args.split}"
    out_dir = RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with (out_dir / "raw.jsonl").open("w", encoding="utf-8") as fh:
        for file_id in (batch.output_file_id, batch.error_file_id):
            if not file_id:
                continue
            for raw in client.files.content(file_id).text.splitlines():
                item = json.loads(raw)
                response = item.get("response") or {}
                ok = response.get("status_code") == 200
                row = {"custom_id": item["custom_id"], "type": "succeeded" if ok else "errored"}
                if ok:
                    row["message"] = response["body"]
                else:
                    row["error"] = item.get("error") or response.get("body")
                seen.add(item["custom_id"])
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        for cid, _ in requests:  # a request missing from both files still counts, as a failure
            if cid not in seen:
                fh.write(json.dumps({"custom_id": cid, "type": "missing"}) + "\n")

    entry = {
        "run_id": run_id, "split": args.split, "configs": configs, "model": args.model,
        "reasoning_effort": args.effort, "questions": len(questions), "requests": len(requests),
        "batch_id": batch.id, "questions_sha256": hashlib.sha256(qpath.read_bytes()).hexdigest(),
        "started": started, "ended": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limit": args.limit,
    }
    with (RUNS / "log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(f"run {run_id} written; score it with: uv run python scripts/score.py {run_id}")


if __name__ == "__main__":
    main()
