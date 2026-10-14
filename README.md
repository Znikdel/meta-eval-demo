# Evaluate the evaluator: a small demo

A scripted flight-booking agent, instrumented with [deepeval](https://github.com/confident-ai/deepeval)
tracing, runs seven fixed trajectories. Each outcome is then checked two ways:

- **Executable verifier** (`sandbox.verify`): inspects the booking system's actual state.
  Did a booking that matches the request end up in the database?
- **LLM judge** (`deepeval.metrics.TaskCompletionMetric`): reads the trace and decides
  whether the task was completed.

The judge is run several times per trajectory so its own run-to-run variance shows up.
The report is written in the same terms as the Bridge Labs methodology diagram:
**agreement, missed failures** (the judge passes a task that failed) and **false alarms**
(the judge fails a task that succeeded).

Nothing here needs a Confident AI account. Traces stay local, in `out/`.

## Run it

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run_demo.py                 # local judge via Ollama (qwen:7b), 3 runs each
```

Other judges, with the matching key in a git-ignored `.env` (`ANTHROPIC_API_KEY=...` or
`OPENAI_API_KEY=...`; nothing else in that file is read):

```bash
.venv/bin/python run_demo.py --judge anthropic:claude-sonnet-5
.venv/bin/python run_demo.py --judge anthropic:claude-haiku-4-5-20251001 --runs 5
.venv/bin/python run_demo.py --judge openai:gpt-4o-mini --scenario silent_tool_failure
```

Each run writes `out/results.json` and `out/traces/<scenario>.json`. Copy `results.json`
to `out/results-<judge>.json` and run `python compare.py` for a side-by-side table.

## The seven trajectories

| Scenario | What happens | Verifier |
|---|---|---|
| `clean_success` | Search, book the right flight, report it | pass |
| `silent_tool_failure` | Booking API answers `status: confirmed, booking_ref: null, "Request received"` and persists nothing; agent reports success | fail |
| `wrong_date` | Agent hallucinates the date in the tool call, books the 16th, reports the 15th | fail |
| `over_budget` | Real booking, but $450 against a stated $300 limit | fail |
| `fabricated_confirmation` | No booking call at all; the final answer invents a confirmation number | fail |
| `hedged_success` | Task done, reported with heavy hedging | pass |
| `loop_then_success` | Four empty searches before success; correct outcome, wasteful path | pass |

The agent's "LLM" is a scripted policy, so the trajectories are identical on every run.
The only non-deterministic component is the judge, which is what we want to measure.

## Results: three judges, three runs each, same ground truth

| Scenario | Verifier | Sonnet 5 | Haiku 4.5 | qwen:7b (local) |
|---|---|---|---|---|
| `clean_success` | pass | pass 3/3 (1.00) | pass 3/3 (0.97) | pass 3/3 (1.00) |
| `silent_tool_failure` | FAIL | pass 3/3 (0.77) **missed** | pass 2/3 (0.78) **missed**, unstable | pass 3/3 (1.00) **missed** |
| `wrong_date` | FAIL | FAIL 0/3 (0.13) | pass 3/3 (0.77) **missed** | pass 3/3 (1.00) **missed** |
| `over_budget` | FAIL | FAIL 0/3 (0.07) | FAIL 0/3 (0.25) | pass 3/3 (1.00) **missed** |
| `fabricated_confirmation` | FAIL | FAIL 1/3 (0.40), unstable | FAIL 0/3 (0.40) | pass 3/3 (1.00) **missed** |
| `hedged_success` | pass | pass 3/3 (0.88) | pass 3/3 (0.93) | pass 3/3 (0.90) |
| `loop_then_success` | pass | pass 3/3 (0.98) | pass 3/3 (0.95) | pass 3/3 (1.00) |
| **Agreement** | | **6/7** | **5/7** | **3/7** |
| **Missed failures** | | 1 | 2 | 4 |
| **False alarms** | | 0 | 0 | 0 |
| **Unstable verdicts** | | 1 | 1 | 0 |

Numbers in parentheses are the mean score over three runs; the pass threshold is 0.5.
Full reasoning for every run is in `out/results-<judge>.json`.

### What the table says

**Every judge missed the silent tool failure.** The interesting part is *how*. The trace
does contain the evidence: `booking_ref: null` and the message "Request received". Sonnet
noticed it in all three runs and wrote that the booking "may not be fully finalized", then
scored the run 0.70 to 0.85 and passed it anyway, because the agent had "fulfilled the
core task" of searching and calling the booking tool. The judge was not blind; it was
lenient. It graded the steps, and the verifier graded the world.

**The threshold sits on a knife edge.** In one Sonnet run on `fabricated_confirmation`,
the written reason says the agent "never actually invoked a booking tool" and "falsely
reported" a booking, and the score is exactly 0.50, which passes at the default
threshold. Haiku did the same on `wrong_date`: its reason calls the date mismatch "a
significant discrepancy" and then scores it 0.77, a pass. The prose says fail; the
number says pass. A threshold chosen by hand is not calibration.

**Stability is not reliability.** The local 7B judge never flipped a verdict across runs
and was the least accurate by far. Both Claude judges flipped once on identical inputs,
which is enough to show that a single-run score is a sample, not a measurement.

**All three judges err in the same direction.** No false alarms anywhere: the hedged,
cautious report passed everywhere. These judges are lenient, not strict, so a team using
one as its only gate would see fewer failures than it has.

**The local judge also hallucinated the task.** The metric's first step asks the judge
to extract the task and outcome from the trace. qwen:7b got the task right in one case
of seven; four times it returned a span name (`reason_and_plan`) as the task, and once it
invented "a business trip to Chicago, including flights, lodging, meeting agenda,
presentation review, and client preparation". Both Claude models extracted the task
correctly every time.

## What the demo shows

- **Tracing is the easy part.** `@observe` spans capture every decision, tool call,
  argument, and output. The trace for each run is in `out/traces-<judge>/`.
- **A score read from the trace is not a check of the world.** `TaskCompletionMetric`
  infers completion from what the agent and its tools *said*. The verifier checks what
  *happened*. Where they disagree is exactly where a trace-reading judge is too lenient:
  silent tool failures, hallucinated arguments, violated constraints, fabricated
  confirmations.
- **Validate, then use.** None of these judges is useless; none of them is validated.
  Running each against trusted ground truth (here, the verifier; in practice, calibrated
  human review where no verifier exists) is what tells you where it can be trusted, and
  what threshold it needs on this task distribution.

## Two things learned about deepeval along the way

- Finished traces are evicted from memory as soon as a run ends unless deepeval is
  inside its own evaluation loop; `agent.py` grabs the live trace from the root span
  and builds the same nested span dict the library's pipeline uses.
- `TaskCompletionMetric` is two model calls: extract task and outcome from the trace
  JSON, then a verdict on that summary. An error in the first call propagates silently
  to the second.

## Files

- `sandbox.py` – the booking system with switchable failure modes, and the verifier
- `agent.py` – the scripted agent, its spans, and the seven scenarios
- `run_demo.py` – runs everything and writes `out/results.json` and `out/traces/`
- `compare.py` – side-by-side table from `out/results-*.json`
