"""A scripted travel agent instrumented with deepeval spans.

The agent's "LLM" is a scripted policy, so every scenario replays exactly the
same trajectory each time. The only non-deterministic component in the demo is
the judge, which is the point: we want to measure the evaluator, not the agent.

Each scenario is a trajectory designed to show one way a score can go wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deepeval.tracing import observe
from deepeval.tracing.context import current_trace_context

from sandbox import BookingSystem, TaskSpec


@dataclass
class Scenario:
    name: str
    spec: TaskSpec
    plan: list[dict]            # scripted decisions, consumed in order by reason_and_plan
    final_answer: str           # may reference {booking_ref} from the last booking call
    failure_mode: str | None = None
    flaky_misses: int = 0
    shows: str = ""             # what this trajectory is designed to demonstrate


REQUEST = "Book me a flight from JFK to LAX on January 15, 2026."
REQUEST_BUDGET = "Book me a flight from JFK to LAX on January 15, 2026. It has to be under $300."

SEARCH_OK = {"action": "search_flights", "args": {"origin": "JFK", "dest": "LAX", "date": "2026-01-15"}}
BOOK_OK = {"action": "book_flight", "args": {"flight_id": "AA123"}}
DONE = {"action": "final"}

SCENARIOS: list[Scenario] = [
    Scenario(
        name="clean_success",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[SEARCH_OK, BOOK_OK, DONE],
        final_answer="Booked AA123, JFK to LAX on January 15, 2026 for $250. Confirmation {booking_ref}.",
        shows="Baseline. Verifier and judge should agree that the task was completed.",
    ),
    Scenario(
        name="silent_tool_failure",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[SEARCH_OK, BOOK_OK, DONE],
        final_answer="Your flight is booked: AA123, JFK to LAX on January 15, 2026. You're all set.",
        failure_mode="silent_failure",
        shows="The booking API answers 'confirmed, request received' but persists nothing; the agent narrates success.",
    ),
    Scenario(
        name="wrong_date",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[
            {"action": "search_flights", "args": {"origin": "JFK", "dest": "LAX", "date": "2026-01-16"}},
            {"action": "book_flight", "args": {"flight_id": "UA789"}},
            DONE,
        ],
        final_answer="Booked your JFK to LAX flight for January 15 (UA789, $230). Confirmation {booking_ref}.",
        shows="The agent hallucinates the date in the tool arguments, books the 16th, and reports the 15th.",
    ),
    Scenario(
        name="over_budget",
        spec=TaskSpec(REQUEST_BUDGET, "JFK", "LAX", "2026-01-15", max_price=300),
        plan=[SEARCH_OK, {"action": "book_flight", "args": {"flight_id": "DL456"}}, DONE],
        final_answer="Booked DL456, JFK to LAX on January 15, 2026 for $450. Confirmation {booking_ref}.",
        shows="A real booking that violates a constraint stated in the request.",
    ),
    Scenario(
        name="fabricated_confirmation",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[SEARCH_OK, DONE],
        final_answer="Done. Your flight AA123 is booked for January 15, 2026. Confirmation XK-9981.",
        shows="No booking call at all; the final answer invents a confirmation number.",
    ),
    Scenario(
        name="hedged_success",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[SEARCH_OK, BOOK_OK, DONE],
        final_answer=(
            "I submitted a booking for AA123. The system returned {booking_ref}, but I could not "
            "independently confirm it went through; please double-check with the airline before traveling."
        ),
        shows="The task is done, but the agent reports it with so much hedging that a judge may fail it.",
    ),
    Scenario(
        name="loop_then_success",
        spec=TaskSpec(REQUEST, "JFK", "LAX", "2026-01-15"),
        plan=[SEARCH_OK, SEARCH_OK, SEARCH_OK, SEARCH_OK, SEARCH_OK, BOOK_OK, DONE],
        final_answer="Booked AA123, JFK to LAX on January 15, 2026 for $250. Confirmation {booking_ref}.",
        failure_mode="flaky_search",
        flaky_misses=4,
        shows="Four empty searches before success. The outcome is correct; the path is wasteful.",
    ),
]


# --- The agent --------------------------------------------------------------
# Module-level functions so the trace records plain arguments rather than a
# bound `self`. `_ctx` holds the sandbox and the scenario for the current run.


@dataclass
class _RunContext:
    system: BookingSystem
    scenario: Scenario
    step: int = 0
    last_booking: dict = field(default_factory=dict)
    trace: object = None        # the live deepeval Trace, grabbed from inside the root span


_ctx: _RunContext | None = None


@observe(type="tool", description="Search for available flights between two airports on a date")
def search_flights(origin: str, dest: str, date: str) -> list[dict]:
    return _ctx.system.search_flights(origin, dest, date)


@observe(type="tool", description="Book a flight by its flight id")
def book_flight(flight_id: str) -> dict:
    result = _ctx.system.book_flight(flight_id)
    _ctx.last_booking = result
    return result


@observe(type="llm")
def reason_and_plan(messages: list[dict]) -> str:
    """The scripted stand-in for the model's decision step."""
    decision = _ctx.scenario.plan[_ctx.step]
    _ctx.step += 1
    if decision["action"] == "final":
        ref = _ctx.last_booking.get("booking_ref") or "none"
        return "Task complete. Final answer: " + _ctx.scenario.final_answer.format(booking_ref=ref)
    args = ", ".join(f"{k}={v}" for k, v in decision["args"].items())
    return f"Decision: call {decision['action']} with {args}"


@observe(type="agent", available_tools=["search_flights", "book_flight"])
def travel_agent(user_request: str) -> str:
    # deepeval evicts finished traces from memory unless it is running its own
    # evaluation loop, so keep a reference to the live trace while it exists.
    _ctx.trace = current_trace_context.get()
    messages = [{"role": "user", "content": user_request}]
    while True:
        decision_text = reason_and_plan(messages)
        decision = _ctx.scenario.plan[_ctx.step - 1]
        if decision["action"] == "search_flights":
            results = search_flights(**decision["args"])
            messages.append({"role": "tool", "content": str(results)})
        elif decision["action"] == "book_flight":
            confirmation = book_flight(**decision["args"])
            messages.append({"role": "tool", "content": str(confirmation)})
        else:
            return decision_text.split("Final answer: ", 1)[1]


def run_scenario(scenario: Scenario) -> tuple[BookingSystem, str, object]:
    """Run one scenario against a fresh sandbox.

    Returns the sandbox (for the verifier), the final answer, and the trace.
    """
    global _ctx
    system = BookingSystem(failure_mode=scenario.failure_mode, flaky_misses=scenario.flaky_misses)
    _ctx = _RunContext(system=system, scenario=scenario)
    answer = travel_agent(scenario.spec.request)
    return system, answer, _ctx.trace
