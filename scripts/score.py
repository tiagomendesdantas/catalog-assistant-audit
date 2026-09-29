"""Grade runs and write data/runs/<run_id>/summary.json.

    uv run python scripts/score.py <run_id> [<run_id> ...]
    uv run python scripts/score.py <test_run_sol> <test_run_luna> --publish

--publish combines test runs (one per model) into web/results.json; examples come from the first.
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


def fmt(e: dict | None) -> str:
    return "–" if not e else f"{e['rate']:.1%} [{e['low']:.1%}, {e['high']:.1%}]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_ids", nargs="+")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--preview-dir", type=Path,
                    help="write a preview from development runs here instead of web/ (for layout checks)")
    args = ap.parse_args()
    if args.preview_dir and args.preview_dir.resolve().is_relative_to(ROOT):
        sys.exit("The preview directory must be outside the repository.")
    log = [json.loads(line) for line in (DATA / "runs" / "log.jsonl").read_text().splitlines()]
    published: dict = {"models": {}, "runs": []}
    for run_id in args.run_ids:
        split = "test" if run_id.endswith("-test") else "dev"
        entry = next(e for e in log if e["run_id"] == run_id)
        summary = score(DATA / "runs" / run_id, DATA / "questions" / "questions.jsonl", split,
                        entry["model"])
        print(f"\n{run_id}")
        for condition, block in summary["conditions"].items():
            for config, s in block["configs"].items():
                h = s["headline"]
                cost = s["cost_usd_standard_per_1000"]
                print(f"  {condition:9s} {config:8s} accuracy {fmt(h['accuracy_when_answerable'])}  "
                      f"unsupported {fmt(h['unsupported_when_not_in_record'])}  "
                      f"neighbor-matches {s['matches_neighbor']}  failed {s['failed']}  "
                      + (f"${cost:.2f}/1k" if cost else ""))
        for config, eff in summary.get("retrieval_effect", {}).items():
            u, a = eff["unsupported_when_not_in_record"], eff["accuracy_when_answerable"]
            print(f"  retrieval − clean {config:8s} unsupported {u['rate']:+.1%} [{u['low']:+.1%}, "
                  f"{u['high']:+.1%}]  accuracy {a['rate']:+.1%} [{a['low']:+.1%}, {a['high']:+.1%}]")
        if args.publish or args.preview_dir:
            if args.publish and split != "test":
                sys.exit(f"Only test runs are published ({run_id} is not).")
            published["models"][entry["model"]] = summary
            published["runs"].append(entry)

    if args.publish or args.preview_dir:
        split = "test" if args.publish else "dev"
        published["test_runs_to_date"] = sum(1 for e in log if e["split"] == "test")
        out_dir = ROOT / "web" if args.publish else args.preview_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps(published, indent=2) + "\n", encoding="utf-8")
        first = args.run_ids[0]
        rows = [json.loads(line) for line in (DATA / "runs" / first / "graded.jsonl").read_text().splitlines()]
        questions = [q for q in read(DATA / "questions" / "questions.jsonl") if q.split == split]
        examples = build_examples(rows, questions, load(), per_stratum=1)
        (out_dir / "examples.json").write_text(json.dumps(examples, indent=2) + "\n", encoding="utf-8")
        if args.publish:
            results_dir = DATA / "results"
            results_dir.mkdir(exist_ok=True)
            for run_id in args.run_ids:
                shutil.copy(DATA / "runs" / run_id / "graded.jsonl", results_dir / f"{run_id}.graded.jsonl")
        print(f"\nwrote {out_dir}/results.json ({len(published['models'])} models) and {len(examples)} examples")


if __name__ == "__main__":
    main()
