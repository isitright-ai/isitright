"""Sequential testing and noise-tolerant minimization, checked by seeded simulation.

The simulations are the evidence for the claims in the docs: the false-claim rate of the sequential
test under no difference, its power and run count under a stated difference, and the recovery rate
of the noise-tolerant minimizer. Seeds are fixed, so the numbers are reproducible.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from isitright.core.minimize import NoisyStatus, minimize_path_noisy
from isitright.core.mutations import AddEntity, Mutation, World
from isitright.core.sequential import (
    Decision,
    PairedSprt,
    RateDecision,
    RateSprt,
    RateSprtConfig,
    SprtConfig,
)
from isitright.core.stochastic import mcnemar_exact
from isitright.core.world import State

SEQUENCES = 2000


def _sequence(rng: random.Random, baseline_rate: float, world_rate: float, cfg: SprtConfig) -> Any:
    test = PairedSprt(cfg)
    while test.decision is Decision.CONTINUE:
        test.add(rng.random() < baseline_rate, rng.random() < world_rate)
    return test


@pytest.mark.parametrize("rate", [0.05, 0.2, 0.5, 0.8])
def test_with_no_true_difference_false_claims_stay_within_alpha_and_sampling_error(
    rate: float,
) -> None:
    cfg = SprtConfig()
    rng = random.Random(20261030)
    claims = sum(
        _sequence(rng, rate, rate, cfg).decision is Decision.RATE_INCREASE for _ in range(SEQUENCES)
    )
    sampling_error = 3 * math.sqrt(cfg.alpha * (1 - cfg.alpha) / SEQUENCES)
    assert claims / SEQUENCES <= cfg.alpha + sampling_error


def test_a_stated_true_difference_is_found_with_power_and_fewer_runs_than_a_fixed_design() -> None:
    cfg = SprtConfig(min_pairs=4, max_pairs=16)
    rng = random.Random(7)
    runs: list[int] = []
    detected = 0
    for _ in range(SEQUENCES):
        test = _sequence(rng, 0.1, 0.7, cfg)
        runs.append(test.pairs)
        detected += test.decision is Decision.RATE_INCREASE
    power = detected / SEQUENCES
    mean_runs = sum(runs) / len(runs)
    # fixed design: k = 16 pairs and the exact McNemar test at alpha 0.05 (the 0.4 rule)
    rng = random.Random(7)
    fixed_detected = 0
    for _ in range(SEQUENCES):
        only_baseline = only_world = 0
        for _ in range(16):
            b, w = rng.random() < 0.1, rng.random() < 0.7
            only_baseline += b and not w
            only_world += w and not b
        fixed_detected += (
            only_world > only_baseline and mcnemar_exact(only_baseline, only_world) < 0.05
        )
    assert power >= 0.8
    assert mean_runs < 16
    assert fixed_detected / SEQUENCES >= 0.8  # the fixed design at 16 pairs, for comparison


def test_the_record_names_the_test_the_looks_the_boundaries_and_the_decision() -> None:
    test = PairedSprt(SprtConfig(min_pairs=2, max_pairs=8))
    for _ in range(8):
        if test.add(False, True) is not Decision.CONTINUE:
            break
    record = test.record()
    assert record.decision is Decision.RATE_INCREASE
    assert record.test == "sequential probability ratio test on discordant pairs"
    assert record.upper_boundary == pytest.approx(math.log(20))
    assert record.lower_boundary == pytest.approx(math.log(0.2))
    assert [look.pair for look in record.looks] == list(range(1, record.pairs + 1))
    assert record.discordant_world_only == record.pairs and record.p_value <= 0.05
    assert "higher failure rate" in record.note


def test_no_discordance_after_the_minimum_pairs_is_counts_only_and_max_pairs_ends_a_tie() -> None:
    quiet = PairedSprt(SprtConfig(min_pairs=4, max_pairs=16))
    for _ in range(4):
        quiet.add(False, False)
    assert quiet.decision is Decision.NO_DISCORDANCE and "counts only" in quiet.record().note
    mixed = PairedSprt(SprtConfig(min_pairs=2, max_pairs=6))
    for world_bad, baseline_bad in [(True, False), (False, True)] * 3:
        mixed.add(baseline_bad, world_bad)
    assert mixed.decision is Decision.UNDECIDED and mixed.record().pairs == 6
    # more pairs against the baseline than for it reaches the lower boundary
    better = PairedSprt(SprtConfig(min_pairs=2, max_pairs=10))
    for _ in range(3):
        better.add(True, False)
    assert better.decision is Decision.NO_INCREASE_AT_EFFECT
    assert better.add(False, True) is Decision.NO_INCREASE_AT_EFFECT  # a stopped test stays stopped


def test_config_rejects_values_that_would_make_the_error_claims_meaningless() -> None:
    for bad in (
        dict(alpha=0.0),
        dict(beta=1.0),
        dict(effect=0.5),
        dict(min_pairs=5, max_pairs=4),
    ):
        with pytest.raises(ValueError):
            SprtConfig(**bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RateSprt(RateSprtConfig(reference=0.6, effect=0.5))


# --- noise-tolerant minimization --------------------------------------------------------------

NAMES = ["a", "b", "c", "d", "e"]
CAUSE = {"b", "d"}
FAIL_WITH_CAUSE = 0.8
FAIL_OTHERWISE = 0.05
RUN_BUDGET = 400


def _toy() -> tuple[World, list[Mutation]]:
    base = World(State({"t": ({"id": "base"},)}, {"t": "id"}))
    path = [
        Mutation(
            family="toy",
            description=name,
            edits=[AddEntity(collection="t", entity={"id": name})],
        )
        for name in NAMES
    ]
    return base, path


def _flaky_agent(rng: random.Random):  # type: ignore[no-untyped-def]
    """Fails with probability 0.8 when both causes are present, else at the noise floor."""

    def run(world: World) -> bool:
        present = {e["id"] for e in world.state.entities("t")}
        rate = FAIL_WITH_CAUSE if present >= CAUSE else FAIL_OTHERWISE
        return rng.random() < rate

    return run


def test_the_minimal_set_is_recovered_in_at_least_95_of_100_seeded_trials() -> None:
    base, path = _toy()
    recovered = 0
    runs_used: list[int] = []
    minimal_claims = 0
    for seed in range(100):
        result = minimize_path_noisy(
            base, path, _flaky_agent(random.Random(seed)), max_runs=RUN_BUDGET
        )
        runs_used.append(result.runs)
        found = {m.description for m in result.path}
        recovered += result.status is NoisyStatus.MINIMIZED and found == CAUSE
        minimal_claims += result.minimal
    assert recovered >= 95
    assert max(runs_used) <= RUN_BUDGET
    assert minimal_claims >= 95


def test_the_result_states_the_confidence_and_the_tests_behind_it() -> None:
    base, path = _toy()
    result = minimize_path_noisy(base, path, _flaky_agent(random.Random(1)))
    assert result.status is NoisyStatus.MINIMIZED and result.minimal
    confidence = result.confidence
    assert confidence["alpha_per_test"] == 0.001 and confidence["beta_per_test"] == 0.001
    assert confidence["bound_a_needed_mutation_was_dropped"] == pytest.approx(
        0.001 * confidence["tests_judged_to_reproduce"]
    )
    assert any(step.decision == "ABOVE" for step in result.steps)
    assert "every single removal" in result.note


def test_a_failure_that_never_shows_returns_the_unminimized_path() -> None:
    base, path = _toy()
    never = minimize_path_noisy(base, path, lambda world: False)
    assert never.status is NoisyStatus.NOT_REPRODUCED and not never.minimal
    assert [m.description for m in never.path] == NAMES


def test_inconsistent_evidence_returns_the_unminimized_path() -> None:
    base, path = _toy()
    rng = random.Random(3)

    def middling(world: World) -> bool:
        # the full path fails well above the floor, but any subset fails at a rate between the two
        # hypotheses, which a capped test cannot decide
        if len(world.state.entities("t")) == len(NAMES) + 1:
            return rng.random() < 0.8
        return rng.random() < 0.22

    result = minimize_path_noisy(
        base, path, middling, config=RateSprtConfig(max_runs=25), max_runs=RUN_BUDGET
    )
    assert result.status is NoisyStatus.INCONSISTENT and not result.minimal
    assert [m.description for m in result.path] == NAMES
    assert "unminimized" in result.note


def test_running_out_of_runs_returns_the_unminimized_path_and_claims_nothing() -> None:
    base, path = _toy()
    result = minimize_path_noisy(base, path, _flaky_agent(random.Random(2)), max_runs=6)
    assert result.status is NoisyStatus.OUT_OF_RUNS and not result.minimal
    assert len(result.path) == len(NAMES)


def test_decisions_of_the_rate_test_cover_both_boundaries() -> None:
    above = RateSprt()
    assert [above.add(True) for _ in range(5)][-1] is RateDecision.ABOVE
    below = RateSprt()
    decisions = [below.add(False) for _ in range(15)]
    assert RateDecision.NOT_ABOVE in decisions
    capped = RateSprt(RateSprtConfig(max_runs=2))
    assert capped.add(True) is None and capped.add(False) is RateDecision.UNDECIDED
