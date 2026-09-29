"""Live smoke test before a batch: one development question per stratum, every configuration.

    uv run python scripts/smoke.py --model <model>

Development questions only; the test split is never touched here. Prints each outcome, the stop
reason, tokens and cost, so a malformed request fails in seconds rather than after a batch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_eval import load_dotenv

from catalog_audit.assistant import EFFORT, evidence_holds, parse_message, request_params
from catalog_audit.catalog import DATA, load, render, render_context
from catalog_audit.grading import grade
from catalog_audit.guard import call_cost_usd
from catalog_audit.questions import read


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", default=EFFORT)
    args = ap.parse_args()
    load_dotenv()
    import openai

    client = openai.OpenAI()
    catalog = load()
    questions = [q for q in read(DATA / "questions" / "questions.jsonl") if q.split == "dev"]
    picks = {(q.stratum, q.condition): q for q in reversed(questions)}  # first per stratum and condition
    total = 0.0
    for q in sorted(picks.values(), key=lambda q: q.qid):
        product = catalog[q.code]
        print(f"\n{q.qid}  {q.text}  [expected {q.expected}]")
        for config in "ABC":
            params = request_params(config, render_context(q.context, catalog), q.text, args.model,
                                    args.effort)
            reply = parse_message(client.chat.completions.create(**params))
            cost = call_cost_usd(args.model, reply.input_tokens, reply.output_tokens)
            total += cost
            routed = config == "C" and not evidence_holds(render(product), reply, q.family)
            g = grade(q.family, q.attribute, q.expected, reply.status, reply.answer, routed=routed)
            print(f"  {config}  {g.outcome:11s} stop={reply.stop_reason:8s} "
                  f"in={reply.input_tokens:5d} out={reply.output_tokens:5d} ${cost:.4f}  "
                  f"answer={reply.answer!r}")
    print(f"\ntotal ${total:.4f} at standard prices · served by {reply.served_by}")


if __name__ == "__main__":
    main()
