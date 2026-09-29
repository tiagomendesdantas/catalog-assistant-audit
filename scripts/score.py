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


def pick_examples(candidates: list[dict], seen_questions: set[str], limit: int = 4) -> list[dict]:
    """A few instructive disagreements per model, one per kind, in this order: an answer the
    evidence check sent to review, an answer invented when the record had none, and a refusal of a
    "not declared" allergen question (the most common refusal). A question already shown for another
    model is skipped. Deterministic: candidates arrive sorted by question id."""
    kinds = [
        lambda ex: ex["answers"].get("C+check", {}).get("outcome") == "routed",
        lambda ex: ex["answers"].get("A", {}).get("outcome") == "unsupported",
        lambda ex: ex["stratum"] == "allergen_no"
        and any(a.get("outcome") == "abstained" for a in ex["answers"].values()),
    ]
    chosen: list[dict] = []
    for kind in kinds:
        for ex in candidates:
            base = ex["qid"].rsplit("-", 1)[0]
            if kind(ex) and base not in seen_questions:
                chosen.append(ex)
                seen_questions.add(base)
                break
    return chosen[:limit]


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
        entry = next(e for e in log if e["run_id"] == run_id and "split" in e)
        resumes = [e for e in log if e["run_id"] == run_id and e.get("event") == "resume"]
        if resumes:
            entry = {**entry, "resumed": resumes}
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
        published["test_runs_to_date"] = sum(1 for e in log if e.get("split") == "test")
        out_dir = ROOT / "web" if args.publish else args.preview_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps(published, indent=2) + "\n", encoding="utf-8")
        questions = [q for q in read(DATA / "questions" / "questions.jsonl") if q.split == split]
        examples: list[dict] = []
        seen: set[str] = set()
        for run_id, entry in zip(args.run_ids, published["runs"], strict=True):
            rows = [json.loads(line) for line in
                    (DATA / "runs" / run_id / "graded.jsonl").read_text().splitlines()]
            candidates = [{**ex, "model": entry["model"]}
                          for ex in build_examples(rows, questions, load(), per_stratum=3)]
            examples += pick_examples(candidates, seen)
        (out_dir / "examples.json").write_text(json.dumps(examples, indent=2) + "\n", encoding="utf-8")
        if args.publish:
            results_dir = DATA / "results"
            results_dir.mkdir(exist_ok=True)
            for run_id in args.run_ids:
                shutil.copy(DATA / "runs" / run_id / "graded.jsonl", results_dir / f"{run_id}.graded.jsonl")
        print(f"\nwrote {out_dir}/results.json ({len(published['models'])} models) and {len(examples)} examples")


if __name__ == "__main__":
    main()
