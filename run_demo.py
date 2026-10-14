"""Evaluate the evaluator.

Runs each scripted trajectory, checks the outcome two ways, and compares them:

  * an executable verifier that inspects the booking system's actual state
    (trusted ground truth), and
  * deepeval's TaskCompletionMetric, an LLM judge that reads the trace.

The judge is run several times per trajectory so its own run-to-run variance
is visible. The report uses the vocabulary from the site's diagram:
agreement, missed failures (judge passes a failed task), and false alarms
(judge fails a completed task).

Usage:
  python run_demo.py                       # local judge: ollama:qwen:7b, 3 runs each
  python run_demo.py --runs 5
  python run_demo.py --judge anthropic:claude-sonnet-5   # needs ANTHROPIC_API_KEY
  python run_demo.py --judge openai:gpt-4o-mini          # needs OPENAI_API_KEY
  python run_demo.py --scenario silent_tool_failure
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("CONFIDENT_TRACE_VERBOSE", "0")


_DOTENV_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}


def _load_dotenv(path: Path) -> None:
    """Read the judge API keys from a local .env (git-ignored) into the environment.

    Only the keys the demo uses are loaded; anything else in the file is ignored.
    Keys already set in the environment win. Values are never printed.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in _DOTENV_KEYS:
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(Path(__file__).parent / ".env")

from deepeval.metrics import TaskCompletionMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402
from deepeval.tracing import trace_manager  # noqa: E402

import agent  # noqa: E402
from sandbox import verify  # noqa: E402

OUT = Path(__file__).parent / "out"


def make_judge(spec: str):
    provider, _, model = spec.partition(":")
    if provider == "ollama":
        from deepeval.models import OllamaModel
        return OllamaModel(model=model, temperature=0)
    if provider == "anthropic":
        from deepeval.models import AnthropicModel
        # No temperature: the current Anthropic API has dropped the parameter, and
        # deepeval only omits it for models its registry already knows about.
        return AnthropicModel(model=model)
    if provider == "openai":
        from deepeval.models import OpenAIModel
        return OpenAIModel(model=model, temperature=0)
    raise SystemExit(f"Unknown judge '{spec}'. Use ollama:<model>, anthropic:<model>, or openai:<model>.")


def judge_once(judge, request: str, answer: str, trace_dict: dict) -> dict:
    metric = TaskCompletionMetric(model=judge, async_mode=False, include_reason=True, threshold=0.5)
    test_case = LLMTestCase(input=request, actual_output=answer)
    test_case._trace_dict = trace_dict  # what deepeval's own pipeline sets before scoring
    t0 = time.time()
    try:
        score = metric.measure(test_case, _show_indicator=False)
    except Exception as exc:  # the judge failed to produce a parsable verdict
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}", "seconds": round(time.time() - t0, 1)}
    return {
        "score": score,
        "pass": bool(metric.success),
        "task": metric.task,
        "outcome": metric.outcome,
        "reason": metric.reason,
        "seconds": round(time.time() - t0, 1),
    }


def classify(verifier_pass: bool, judge_pass: bool) -> str:
    if verifier_pass and judge_pass:
        return "agree: completed"
    if not verifier_pass and not judge_pass:
        return "agree: failed"
    if judge_pass and not verifier_pass:
        return "MISSED FAILURE (judge passed a failed task)"
    return "FALSE ALARM (judge failed a completed task)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", default=os.environ.get("JUDGE", "ollama:qwen:7b"))
    ap.add_argument("--runs", type=int, default=3, help="judge runs per trajectory")
    ap.add_argument("--scenario", default=None, help="run a single scenario by name")
    args = ap.parse_args()

    scenarios = [s for s in agent.SCENARIOS if args.scenario in (None, s.name)]
    if not scenarios:
        raise SystemExit(f"No scenario named {args.scenario!r}. Known: {[s.name for s in agent.SCENARIOS]}")

    judge = make_judge(args.judge)
    (OUT / "traces").mkdir(parents=True, exist_ok=True)
    rows = []

    print(f"\nJudge: {args.judge}   runs per trajectory: {args.runs}\n")
    for sc in scenarios:
        system, answer, trace = agent.run_scenario(sc)
        trace_dict = trace_manager.create_nested_spans_dict(trace.root_spans[0])
        v_pass, v_detail = verify(system, sc.spec)

        runs = [judge_once(judge, sc.spec.request, answer, trace_dict) for _ in range(args.runs)]
        valid = [r for r in runs if "pass" in r]
        passes = sum(r["pass"] for r in valid)
        majority = passes * 2 > len(valid) if valid else None
        flips = min(passes, len(valid) - passes)
        scores = [r["score"] for r in valid]
        verdict = classify(v_pass, majority) if majority is not None else "judge produced no verdict"

        row = {
            "scenario": sc.name,
            "shows": sc.shows,
            "request": sc.spec.request,
            "final_answer": answer,
            "verifier": {"pass": v_pass, "detail": v_detail},
            "judge": {
                "majority_pass": majority,
                "passes": passes,
                "valid_runs": len(valid),
                "runs": args.runs,
                "mean_score": round(statistics.mean(scores), 2) if scores else None,
                "flips": flips,
            },
            "verdict": verdict,
            "judge_runs": runs,
        }
        rows.append(row)
        (OUT / "traces" / f"{sc.name}.json").write_text(json.dumps({"trace": trace_dict, **row}, indent=2, default=str))

        tag = "pass" if v_pass else "FAIL"
        jtag = "pass" if majority else ("FAIL" if majority is not None else "n/a")
        print(f"{sc.name:<24} verifier {tag:<4}  judge {jtag:<4} ({passes}/{len(valid)} pass, mean {row['judge']['mean_score']})  -> {verdict}")
        print(f"{'':<24} verifier: {v_detail}")
        if valid:
            print(f"{'':<24} judge:    {valid[0]['reason'][:220]}")
        for r in runs:
            if "error" in r:
                print(f"{'':<24} judge error: {r['error']}")
        print()

    # Summary in the diagram's terms.
    scored = [r for r in rows if r["judge"]["majority_pass"] is not None]
    agree = sum(1 for r in scored if r["verdict"].startswith("agree"))
    missed = sum(1 for r in scored if r["verdict"].startswith("MISSED"))
    false_alarms = sum(1 for r in scored if r["verdict"].startswith("FALSE"))
    unstable = [r["scenario"] for r in scored if r["judge"]["flips"] > 0]
    print("=" * 78)
    print(f"Agreement {agree}/{len(scored)}   Missed failures {missed}   False alarms {false_alarms}   "
          f"Unstable verdicts {len(unstable)}" + (f" ({', '.join(unstable)})" if unstable else ""))
    print("=" * 78)

    summary = {"judge": args.judge, "runs": args.runs, "agreement": agree, "scored": len(scored),
               "missed_failures": missed, "false_alarms": false_alarms, "unstable": unstable, "rows": rows}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nTraces and results written to {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}/")


if __name__ == "__main__":
    main()
