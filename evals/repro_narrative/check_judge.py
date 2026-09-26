"""Known-negative check for the pairwise judge. CALLS THE REAL API (3 judge calls).

    uv run python -m evals.repro_narrative.check_judge --case RP2

Against a frozen baseline reference, an empty narrative, an "I don't know"
narrative and a confident narrative about a different incident must all lose
(win == 0). Nothing is written to results.jsonl.
"""

import argparse
import json
import random
from pathlib import Path

import anthropic
from dotenv import find_dotenv, load_dotenv

from evals.repro_narrative import grade
from evals.repro_narrative.build_cases import CASES_DIR
from evals.repro_narrative.run import FLOW, cost


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="RP2")
    parser.add_argument("--wrong-from", default="S05", help="case whose frozen narrative plays the wrong answer")
    parser.add_argument("--only", help="run just the negatives whose name starts with this (e.g. wrong)")
    args = parser.parse_args()
    load_dotenv(find_dotenv(usecwd=True))
    packet = json.loads((CASES_DIR / f"{args.case}.json").read_text())["packet"]
    reference = json.loads((FLOW / "baseline" / "ref" / f"{args.case}.json").read_text())
    wrong = json.loads((FLOW / "baseline" / "ref" / f"{args.wrong_from}.json").read_text())
    negatives = {
        "empty": None,
        "i_dont_know": {"summary": {"text": "I don't know how to reproduce this incident.", "cites": ["incident"]},
                        "steps_prose": [], "conditions": [], "missing_evidence_questions": []},
        f"wrong_incident({args.wrong_from})": wrong,
    }
    client = anthropic.Anthropic(max_retries=2)
    total, ok = 0.0, True
    for name, candidate in negatives.items():
        if args.only and not name.startswith(args.only):
            continue
        verdict = grade.judge(client, packet, candidate, reference, random.Random(name))
        spent = cost(verdict["judge_model"], verdict["judge_usage"])
        total += spent
        ok &= verdict["win"] == 0.0
        print(f"{'OK  ' if verdict['win'] == 0.0 else 'FAIL'} {name}: verdict={verdict['verdict']} "
              f"(candidate={verdict['candidate_position']}) faults={len(verdict['candidate_faults'])} ${spent:.3f}")
        print(f"       {verdict['reasoning'][:300]}")
    print(f"judge-negative spend: ${total:.3f}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
