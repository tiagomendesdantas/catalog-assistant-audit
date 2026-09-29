"""Grade a run and write data/runs/<run_id>/summary.json.

    uv run python scripts/score.py <run_id>
    uv run python scripts/score.py <run_id> --publish   # also copy to web/results.json (test runs only)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog_audit.catalog import DATA, load
from catalog_audit.questions import read
from catalog_audit.report import build_examples, score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()
    run_dir = DATA / "runs" / args.run_id
    split = "test" if args.run_id.endswith("-test") else "dev"
    log = [json.loads(line) for line in (DATA / "runs" / "log.jsonl").read_text().splitlines()]
    entry = next(e for e in log if e["run_id"] == args.run_id)
    summary = score(run_dir, DATA / "questions" / "questions.jsonl", split, entry["model"])
    for config, s in summary["configs"].items():
        h = s["headline"]
        acc, uns = h["accuracy_when_answerable"], h["unsupported_when_not_in_record"]
        cost = s["cost_usd_standard_per_1000"]
        print(f"{config:8s} accuracy {acc['rate']:.1%} [{acc['low']:.1%}, {acc['high']:.1%}]  "
              f"unsupported {uns['rate']:.1%} [{uns['low']:.1%}, {uns['high']:.1%}]  "
              f"failed {s['failed']}  " + (f"${cost:.2f}/1k" if cost else "cost unknown"))
    if args.publish:
        if split != "test":
            sys.exit("Only test runs are published.")
        summary["run"] = entry
        summary["test_runs_to_date"] = sum(1 for e in log if e["split"] == "test")
        out = ROOT / "web" / "results.json"
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        rows = [json.loads(line) for line in (run_dir / "graded.jsonl").read_text().splitlines()]
        questions = [q for q in read(DATA / "questions" / "questions.jsonl") if q.split == "test"]
        examples = build_examples(rows, questions, load())
        (ROOT / "web" / "examples.json").write_text(json.dumps(examples, indent=2) + "\n", encoding="utf-8")
        results_dir = DATA / "results"
        results_dir.mkdir(exist_ok=True)
        shutil.copy(run_dir / "graded.jsonl", results_dir / f"{args.run_id}.graded.jsonl")
        print(f"published {out} and {len(examples)} examples")


if __name__ == "__main__":
    main()
