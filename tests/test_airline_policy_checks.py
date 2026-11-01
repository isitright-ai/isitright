"""The airline policy checks for certificates and flight changes (no tau2 needed)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "examples" / "agents" / "airline"))

from policy_checks import certificate_problems, flight_change_problems


def _state(
    *,
    membership: str = "regular",
    insurance: str = "no",
    cabin: str = "economy",
    status: str = "available",
    passengers: int = 2,
    flight_type: str = "one_way",
) -> dict[str, Any]:
    leg = {"flight_number": "F1", "date": "2024-05-20"}
    return {
        "users": {"u": {"membership": membership, "reservations": ["R"]}},
        "reservations": {
            "R": {
                "reservation_id": "R",
                "insurance": insurance,
                "cabin": cabin,
                "passengers": [{}] * passengers,
                "flights": [leg],
                "origin": "AAA",
                "destination": "BBB",
                "flight_type": flight_type,
            }
        },
        "flights": {
            "F1": {
                "origin": "AAA",
                "destination": "BBB",
                "dates": {"2024-05-20": {"status": status}},
            },
            "F2": {"origin": "AAA", "destination": "BBB", "dates": {}},
            "F3": {"origin": "CCC", "destination": "BBB", "dates": {}},
            "F4": {"origin": "AAA", "destination": "DDD", "dates": {}},
        },
    }


def _certificate(amount: int, user: str = "u") -> list[dict[str, Any]]:
    return [
        {
            "name": "send_certificate",
            "is_error": False,
            "arguments": {"user_id": user, "amount": amount},
        }
    ]


def _change(flights: list[str], reservation: str = "R") -> list[dict[str, Any]]:
    return [
        {
            "name": "update_reservation_flights",
            "is_error": False,
            "arguments": {
                "reservation_id": reservation,
                "flights": [{"flight_number": f, "date": "2024-05-20"} for f in flights],
            },
        }
    ]


def test_a_certificate_for_a_cancelled_flight_to_an_eligible_customer_is_fine() -> None:
    state = _state(membership="gold", status="cancelled")
    assert certificate_problems(state, state, _certificate(200)) == []


@pytest.mark.parametrize(
    ("state", "amount", "words"),
    [
        (_state(status="cancelled"), 200, "no insurance and no business"),
        (_state(membership="gold", status="cancelled"), 100, "matches no cancelled"),
        (_state(membership="gold"), 200, "matches no cancelled"),
    ],
)
def test_a_certificate_to_an_ineligible_customer_or_for_a_wrong_amount_is_reported(
    state: dict[str, Any], amount: int, words: str
) -> None:
    (problem,) = certificate_problems(state, state, _certificate(amount))
    assert words in problem


def test_insurance_or_business_make_a_customer_eligible_and_delays_pay_half() -> None:
    insured = _state(insurance="yes", status="delayed")
    assert certificate_problems(insured, insured, _certificate(100)) == []
    business = _state(cabin="business", status="delayed")
    assert certificate_problems(business, business, _certificate(50)) != []


def test_a_certificate_that_failed_or_went_to_someone_else() -> None:
    state = _state(membership="gold", status="cancelled")
    failed = [{**_certificate(5)[0], "is_error": True}]
    assert certificate_problems(state, state, failed) == []
    assert "not the customer" in certificate_problems(state, state, _certificate(200, "x"))[0]


def test_a_flight_change_that_keeps_the_trip_is_fine() -> None:
    state = _state()
    assert flight_change_problems(state, state, _change(["F2"])) == []


@pytest.mark.parametrize(
    ("state", "flights", "words"),
    [
        (_state(cabin="basic_economy"), ["F2"], "basic economy"),
        (_state(), ["F3"], "now starts at CCC"),
        (_state(), ["F4"], "no longer reaches BBB"),
    ],
)
def test_a_flight_change_that_breaks_the_policy_is_reported(
    state: dict[str, Any], flights: list[str], words: str
) -> None:
    problems = flight_change_problems(state, state, _change(flights))
    assert any(words in p for p in problems)
