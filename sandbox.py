"""A tiny flight-booking system the agent acts on, plus the executable verifier.

The verifier is the "trusted ground truth" side of the diagram: it checks the
world state (what was actually booked), not what the agent said about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


FLIGHTS = [
    {"flight_id": "AA123", "origin": "JFK", "dest": "LAX", "date": "2026-01-15", "price": 250},
    {"flight_id": "DL456", "origin": "JFK", "dest": "LAX", "date": "2026-01-15", "price": 450},
    {"flight_id": "UA789", "origin": "JFK", "dest": "LAX", "date": "2026-01-16", "price": 230},
    {"flight_id": "AA321", "origin": "LAX", "dest": "JFK", "date": "2026-01-15", "price": 260},
]


@dataclass
class TaskSpec:
    """What the user actually asked for, in checkable terms."""

    request: str
    origin: str
    dest: str
    date: str
    max_price: int | None = None


@dataclass
class BookingSystem:
    """In-memory booking backend with switchable failure modes.

    failure_mode:
      None              - behaves correctly
      "silent_failure"  - book_flight answers 200-OK style ("request received")
                          but never persists a booking
      "flaky_search"    - the first `flaky_misses` searches return an empty list
    """

    failure_mode: str | None = None
    flaky_misses: int = 0
    bookings: dict[str, dict] = field(default_factory=dict)
    _search_calls: int = 0
    _ref_counter: int = 1000

    def search_flights(self, origin: str, dest: str, date: str) -> list[dict]:
        self._search_calls += 1
        if self.failure_mode == "flaky_search" and self._search_calls <= self.flaky_misses:
            return []
        return [f for f in FLIGHTS if f["origin"] == origin and f["dest"] == dest and f["date"] == date]

    def book_flight(self, flight_id: str) -> dict:
        if self.failure_mode == "silent_failure":
            # The classic silent tool failure: no error, no booking.
            return {"status": "confirmed", "booking_ref": None, "message": "Request received"}
        flight = next((f for f in FLIGHTS if f["flight_id"] == flight_id), None)
        if flight is None:
            return {"status": "error", "message": f"Unknown flight {flight_id}"}
        self._ref_counter += 1
        ref = f"BL-{self._ref_counter}"
        self.bookings[ref] = {"booking_ref": ref, **flight}
        return {"status": "confirmed", "booking_ref": ref, "flight_id": flight_id, "date": flight["date"], "price": flight["price"]}


def verify(system: BookingSystem, spec: TaskSpec) -> tuple[bool, str]:
    """Executable verifier: did the world end up in the state the user asked for?"""
    matches = [
        b for b in system.bookings.values()
        if b["origin"] == spec.origin and b["dest"] == spec.dest and b["date"] == spec.date
    ]
    if not matches:
        if system.bookings:
            got = ", ".join(f"{b['flight_id']} on {b['date']} (${b['price']})" for b in system.bookings.values())
            return False, f"no booking matches {spec.origin}->{spec.dest} on {spec.date}; found: {got}"
        return False, "no booking exists"
    if spec.max_price is not None:
        within = [b for b in matches if b["price"] <= spec.max_price]
        if not within:
            prices = ", ".join(f"${b['price']}" for b in matches)
            return False, f"booked flight exceeds the ${spec.max_price} limit ({prices})"
        matches = within
    b = matches[0]
    return True, f"booking {b['booking_ref']}: {b['flight_id']} {b['origin']}->{b['dest']} on {b['date']} (${b['price']})"
