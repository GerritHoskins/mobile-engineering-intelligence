"""Runner for the reproduction-narrative eval. CALLS THE REAL CLAUDE API.

    uv run python -m evals.repro_narrative.run --variant baseline [--reps 1] [--cases RP2,S05]
    uv run python -m evals.repro_narrative.run --variant v1 --model claude-sonnet-5 --effort high

Each (case, rep) goes through the app's real entry point, app.llm.service.explain
(regenerate=True, so stored outputs are never served), against a dedicated
*_eval database. Output lands in .claude/hillclimb/repro_narrative/<variant>/:
results.jsonl (one row per scored attempt, written as it completes),
traces/<case>_rep<k>.json, and errors.jsonl for attempts that produced
nothing scorable. The baseline's rep-0 narratives are frozen to baseline/ref/
and every other variant is judged pairwise against them.

The runner refuses to start when this file or anything in _state.json's
harness_paths (grader, prompts, client, citation check) changed since a human
last recorded approval with --approve-harness (which only records, never runs).
"""

import os
from urllib.parse import urlparse

# Stored outputs are written by explain(); never into the dev DB (verify_llm's
# stored outputs live there). Must run before any app.db import.
EVAL_DATABASE_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql+psycopg://mei:mei@localhost:5432/mei_eval")
if not urlparse(EVAL_DATABASE_URL).path.rstrip("/").endswith("_eval"):
    raise RuntimeError(f"Refusing to run the eval against a non-eval database: {EVAL_DATABASE_URL}")
os.environ["DATABASE_URL"] = EVAL_DATABASE_URL

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import anthropic  # noqa: E402
from dotenv import find_dotenv, load_dotenv  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.llm import config  # noqa: E402
from app.llm.client import AnthropicLLM, LLMError, LLMRefused, LLMResult, LLMTruncated, LLMUnavailable  # noqa: E402
from app.llm.service import explain  # noqa: E402
from app.orgs import load_org  # noqa: E402
from evals.repro_narrative import grade  # noqa: E402
from evals.repro_narrative.build_cases import CASES_DIR  # noqa: E402

FLOW = Path(".claude/hillclimb/repro_narrative")
ORG = load_org("demo")
MAX_ATTEMPTS = 4
# $/MTok (input, output), first-party list prices -- used only for the printed summary.
PRICES = {"claude-opus-5": (5, 25), "claude-sonnet-5": (2, 10), "claude-opus-5-5": (4, 20),
          "claude-haiku-4-5": (1, 5), "claude-fable-5-1": (10, 50)}


# ------------------------------------------------------------------ gate


def harness_gate(flow: Path, approve: bool) -> None:
    state_path = flow / "_state.json"
    state = json.loads(state_path.read_text())
    paths = [Path(__file__).resolve()] + [Path(p) for p in state.get("harness_paths", [])]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.name).encode() + b"\0" + path.read_bytes())
    sha = digest.hexdigest()
    if state.get("harness_sha") == sha:
        return
    if approve:
        state["harness_sha"] = sha
        state_path.write_text(json.dumps(state, indent=1) + "\n")
        sys.exit(f"harness approved: sha256 {sha[:12]} over {len(paths)} files (nothing was run)")
    what = "no approved harness sha" if state.get("harness_sha") is None else "harness changed since approval"
    sys.exit(f"{what} (now {sha[:12]}). Review the runner/grader, then re-run once with --approve-harness.")


# ------------------------------------------------------------- recording


class Recorder:
    """Delegates to the real client and keeps what explain() does not return:
    the exact prompt, raw output, served model, usage and latency -- also for
    attempts that fail after being billed."""

    def __init__(self, inner: AnthropicLLM):
        self.inner = inner
        self.system = self.user = None
        self.call: dict = {}

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        self.system, self.user = system, user
        started = time.monotonic()
        try:
            result = self.inner.generate(system=system, user=user, schema=schema)
        except LLMError as error:
            self.call = {"ok": False, "model": error.served_model, "usage": error.usage,
                         "latency_s": round(time.monotonic() - started, 2)}
            raise
        self.call = {"ok": True, "model": result.model, "usage": result.usage, "data": result.data,
                     "fallback_used": result.fallback_used, "latency_s": round(time.monotonic() - started, 2)}
        return result


def served_as_requested(served: str | None, requested: str) -> bool:
    # Tolerate documented alias -> dated snapshot resolution only.
    return bool(served) and (served == requested or served.startswith(requested + "-"))


class Outcome(Exception):
    """An attempt that ends in errors.jsonl rather than results.jsonl."""

    def __init__(self, failure_class: str, message: str, model: str | None = None, usage: dict | None = None):
        super().__init__(message)
        self.failure_class, self.model, self.usage = failure_class, model, usage


# ------------------------------------------------------------------ run


def load_cases(only: set[str] | None) -> list[dict]:
    cases = [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]
    return [c for c in cases if not only or c["id"] in only]


def tags(case: dict) -> list[str]:
    return [case["source"]] + [c for c in case["covers"] if not c.startswith(("precondition:", "varies:"))]


def run_one(case: dict, rep: int, args, llm: AnthropicLLM, judge_client: anthropic.Anthropic, flow: Path) -> dict:
    packet = case["packet"]
    subject = f"{case['id']}~{args.variant}~r{rep}"  # unique per attempt: stored rows never collide
    recorder = Recorder(llm)
    retries = 0
    result = failure = None
    started = time.monotonic()
    while True:
        recorder.call = {}
        try:
            with SessionLocal() as session:
                result = explain(session, ORG, "repro_narrative", subject, packet, recorder, regenerate=True)
            break
        except LLMUnavailable as error:
            retries += 1
            if args.timeout_s and time.monotonic() - started > args.timeout_s:
                raise Outcome("timeout", f"wall-clock ceiling {args.timeout_s}s reached after {retries} attempts")
            if retries >= MAX_ATTEMPTS:
                raise Outcome("serving_error", f"{error} (after {retries} attempts)")
            time.sleep(min(60, 2 ** retries) + random.uniform(0, 1))
        except LLMTruncated:
            failure = "truncated"
            break
        except LLMRefused as error:
            failure = f"refused:{error.category}"
            break
        except LLMError as error:
            if not recorder.call or (not recorder.call["ok"] and recorder.call.get("usage") is None):
                # The API rejected the request or the client is misconfigured: plumbing, not the model.
                raise Outcome("harness_error", str(error))
            failure = f"invalid_output:{error}"  # billed and answered, but unusable: a graded failure
            break

    call = recorder.call
    if not served_as_requested(call.get("model"), args.model):
        raise Outcome("served_model_mismatch", f"served by {call.get('model')}, requested {args.model}",
                      call.get("model"), call.get("usage"))
    if result is not None and result["cached"]:
        raise Outcome("harness_error", "explain() served a stored output despite regenerate=True",
                      call.get("model"), call.get("usage"))

    row = {"prompt_id": case["id"], "prompt": case["note"], "tags": tags(case), "variant": args.variant,
           "rep": rep, "model": call.get("model"), "usage": call.get("usage"),
           "latency_s": call.get("latency_s"), "out_tokens": (call.get("usage") or {}).get("output_tokens"),
           "effort": args.effort, "prompt_version": config.PROMPT_VERSION,
           "meta": {"retries": retries, "subject": subject, "fallback_used": call.get("fallback_used")}}
    trace = [{"role": "system", "content": recorder.system}, {"role": "user", "content": recorder.user}]

    if failure in ("truncated",) or (failure or "").startswith("refused"):
        row.update(status=failure.split(":")[0], stop_reason="max_tokens" if failure == "truncated" else "refusal",
                   grade={})
        trace.append({"role": "assistant", "content": f"({failure})"})
        return {"row": row, "trace": trace}

    output = result["output"] if result else None
    rejected = result["rejected_claims"] if result else []
    scores = grade.programmatic(packet, output, rejected) if result else {
        "grounded": 0.0, "coverage": 0.0, "steps_in_order": 0.0, "gaps_questioned": 0.0}
    explanation = {}
    row["meta"]["rejected_claims"] = rejected
    if failure:
        row["meta"]["failure"] = failure
    narrative = grade.render_narrative(output) if result else f"({failure})"
    if rejected:
        narrative += "\n\nREJECTED by the citation check:\n" + "\n".join(
            f"({r['reason']}) {r['text']}  (cites: {', '.join(r['cites'])})" for r in rejected)
    trace.append({"role": "assistant", "content": narrative})

    if args.variant == "baseline":
        scores["win"] = 0.5  # the reference itself: neutral by definition
        if rep == 0 and output is not None:
            (flow / "baseline" / "ref").mkdir(parents=True, exist_ok=True)
            ref_path = flow / "baseline" / "ref" / f"{case['id']}.json"
            if not ref_path.exists():  # frozen: never regenerated
                ref_path.write_text(json.dumps(output, indent=1, sort_keys=True) + "\n")
    elif output is None:
        scores["win"] = 0.0  # produced nothing usable; no judge call needed
    else:
        reference = json.loads((flow / "baseline" / "ref" / f"{case['id']}.json").read_text())
        rng = random.Random(f"{case['id']}:{rep}:{args.variant}")
        verdict = judge_with_retries(judge_client, packet, output, reference, rng)
        scores["win"] = verdict["win"]
        scores["faults"] = float(len(verdict["candidate_faults"]))
        scores["both_bad"] = float(verdict["verdict"] == "both_bad")
        explanation["win"] = verdict["reasoning"]
        row.update(judge_model=verdict["judge_model"], judge_usage=verdict["judge_usage"])
        row["meta"].update(verdict=verdict["verdict"], candidate_position=verdict["candidate_position"],
                           candidate_faults=verdict["candidate_faults"],
                           reference_faults=verdict["reference_faults"])
        trace.append({"role": "tool_call", "name": "judge",
                      "content": f"Blind pairwise vs frozen baseline; this output shown as "
                                 f"{verdict['candidate_position']}.\n\nReference narrative:\n"
                                 + grade.render_narrative(reference)})
        trace.append({"role": "tool_result", "name": "judge", "content": json.dumps(
            {k: verdict[k] for k in ("verdict", "win", "candidate_faults", "reference_faults", "reasoning")},
            indent=1)})
    trace.append({"role": "tool_result", "name": "programmatic", "content": json.dumps(scores, indent=1)})
    row.update(status="ok", stop_reason="end_turn", grade=scores, explanation=explanation,
               wall_s=round(time.monotonic() - started, 2))
    return {"row": row, "trace": trace}


def judge_with_retries(client, packet, output, reference, rng) -> dict:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return grade.judge(client, packet, output, reference, rng)
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as error:
            if attempt == MAX_ATTEMPTS:
                raise Outcome("grader_error", f"judge unavailable: {error}")
            time.sleep(min(60, 2 ** attempt) + random.uniform(0, 1))
        except grade.JudgeError as error:
            raise Outcome("grader_error", str(error), grade.JUDGE_MODEL, error.usage)


def cost(model: str | None, usage: dict | None) -> float:
    if not model or not usage:
        return 0.0
    price_in, price_out = next((p for m, p in PRICES.items() if model.startswith(m)), (0, 0))
    return (usage.get("input_tokens", 0) * price_in + usage.get("output_tokens", 0) * price_out) / 1e6


def summarize(out_dir: Path, wall: float) -> None:
    rows = [json.loads(line) for line in (out_dir / "results.jsonl").read_text().splitlines()] \
        if (out_dir / "results.jsonl").exists() else []
    errors = [json.loads(line) for line in (out_dir / "errors.jsonl").read_text().splitlines()] \
        if (out_dir / "errors.jsonl").exists() else []
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n{out_dir.name}: {len(ok)} scored, {len(rows) - len(ok)} not ok "
          f"({', '.join(sorted({r['status'] for r in rows if r['status'] != 'ok'})) or '-'}), {len(errors)} errors")
    for metric in ("win", "faults", "both_bad", "grounded", "coverage", "steps_in_order", "gaps_questioned"):
        per_case: dict[str, list[float]] = {}
        for r in ok:
            if metric in r["grade"]:
                per_case.setdefault(r["prompt_id"], []).append(r["grade"][metric])
        means = [statistics.mean(v) for v in per_case.values()]
        if not means:
            continue
        half = 1.96 * statistics.stdev(means) / len(means) ** 0.5 if len(means) > 1 else float("nan")
        print(f"  {metric:16} {statistics.mean(means):.3f} ± {half:.3f}  (n={len(means)} cases)")
    gen = [cost(r["model"], r["usage"]) for r in rows] + \
          [cost(e.get("model"), e.get("usage")) for e in errors if e.get("failure_class") != "grader_error"]
    judge_cost = [cost(r.get("judge_model"), r.get("judge_usage")) for r in rows] + \
                 [cost(e.get("model"), e.get("usage")) for e in errors if e.get("failure_class") == "grader_error"]
    per_case = sorted(cost(r["model"], r["usage"]) + cost(r.get("judge_model"), r.get("judge_usage")) for r in rows)
    lat = sorted(r["latency_s"] for r in ok if r.get("latency_s"))
    outs = sorted(r["out_tokens"] for r in ok if r.get("out_tokens"))
    print(f"  cost: generation ${sum(gen):.3f} + judge ${sum(judge_cost):.3f} = ${sum(gen) + sum(judge_cost):.3f}")
    if per_case:
        print(f"  per case: min ${per_case[0]:.3f} / median ${statistics.median(per_case):.3f} / max ${per_case[-1]:.3f}")
    if lat:
        print(f"  latency: median {statistics.median(lat):.1f}s (max {lat[-1]:.1f}s); "
              f"output tokens median {statistics.median(outs):.0f} (max {outs[-1]})")
    print(f"  wall clock this run: {wall:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", type=Path, default=FLOW)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--model", default=config.MODEL)
    parser.add_argument("--effort", default=config.EFFORT)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--approve-harness", action="store_true")
    args = parser.parse_args()
    if args.variant != "baseline" and not (args.variant.startswith("v") and args.variant[1:].isdigit()):
        sys.exit("--variant must be 'baseline' or v<N> (the report builder ignores anything else)")

    harness_gate(args.flow, args.approve_harness)
    load_dotenv(find_dotenv(usecwd=True))
    config.MODEL, config.EFFORT = args.model, args.effort  # read at call time by the client and explain()
    out_dir = args.flow / args.variant
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    results_path, errors_path = out_dir / "results.jsonl", out_dir / "errors.jsonl"
    done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results_path.read_text().splitlines())} \
        if results_path.exists() else set()
    todo = [(c, rep) for c in load_cases(set(args.cases.split(",")) if args.cases else None)
            for rep in range(args.reps) if (c["id"], rep) not in done]
    if args.variant != "baseline":
        missing = [c["id"] for c, _ in todo if not (args.flow / "baseline" / "ref" / f"{c['id']}.json").exists()]
        if missing:
            sys.exit(f"No frozen baseline reference for {sorted(set(missing))}; run the baseline first.")
    print(f"{args.variant}: {len(todo)} attempts on {args.model} (effort {args.effort}), {len(done)} already done")

    llm = AnthropicLLM(anthropic.Anthropic(max_retries=0, timeout=args.timeout_s))
    judge_client = anthropic.Anthropic(max_retries=0, timeout=args.timeout_s)
    lock = threading.Lock()
    started = time.monotonic()

    def attempt(case: dict, rep: int) -> None:
        try:
            out = run_one(case, rep, args, llm, judge_client, args.flow)
        except Outcome as outcome:
            record = {"prompt_id": case["id"], "rep": rep, "failure_class": outcome.failure_class,
                      "message": str(outcome), "model": outcome.model, "usage": outcome.usage}
        except Exception as error:  # noqa: BLE001 -- anything else is a harness failure, never a score
            record = {"prompt_id": case["id"], "rep": rep, "failure_class": "harness_error",
                      "message": f"{type(error).__name__}: {error}", "model": None, "usage": None}
        else:
            (out_dir / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(out["trace"], indent=1))
            with lock, results_path.open("a") as f:
                f.write(json.dumps(out["row"], default=str) + "\n")
            print(f"  {case['id']} rep{rep}: {out['row']['status']} {out['row']['grade']}")
            return
        with lock, errors_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        print(f"  {case['id']} rep{rep}: ERROR {record['failure_class']}: {record['message']}")

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        # Per-case ceiling: each HTTP call is capped at --timeout-s by the client, and
        # run_one stops retrying once the case as a whole has used it up.
        for future in [pool.submit(attempt, c, rep) for c, rep in todo]:
            future.result()
    summarize(out_dir, time.monotonic() - started)


if __name__ == "__main__":
    main()
