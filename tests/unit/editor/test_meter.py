"""The money meter (docs/EDITOR.md §8, D37): exact costs, Haiku's long tier, the $5 guard."""

from decimal import Decimal

import pytest

from reel_studio.core import config
from reel_studio.core.errors import CostCapReached
from reel_studio.editor import meter

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def _meter(cap: str = "5.0") -> meter.Meter:
    return meter.Meter(config.load().prices, Decimal(cap))


def test_measured_baseline_costs_exactly_its_cache_parts() -> None:
    usage = meter.Usage(input_tokens=0, output_tokens=0, cache_write=130_000, cache_read=1_640_000)

    cost = _meter().cost(SONNET, usage)

    assert cost == Decimal("0.164") + Decimal("0.325")


def test_every_part_is_priced_per_million() -> None:
    usage = meter.Usage(
        input_tokens=1_000_000, output_tokens=1_000_000, cache_write=0, cache_read=0
    )

    assert _meter().cost(SONNET, usage) == Decimal("12.00")  # $2 in + $10 out (F05)


@pytest.mark.parametrize(("prompt", "price"), [(100_000, "0.10"), (100_001, "0.50")])
def test_haiku_switches_to_the_long_tier_above_100k_prompt_tokens(prompt: int, price: str) -> None:
    usage = meter.Usage(input_tokens=prompt, output_tokens=0, cache_write=0, cache_read=0)

    cost = _meter().cost(HAIKU, usage)

    assert cost == Decimal(price) * prompt / 1_000_000


def test_long_tier_counts_cached_tokens_in_the_prompt_size() -> None:
    usage = meter.Usage(input_tokens=10, output_tokens=0, cache_write=0, cache_read=100_000)

    cost = _meter().cost(HAIKU, usage)

    assert cost == (Decimal("0.50") * 10 + Decimal("0.05") * 100_000) / 1_000_000


def test_worst_case_uses_the_higher_of_input_and_cache_write() -> None:
    worst = _meter().worst_case(SONNET, prompt_tokens=100_000, max_tokens=16_000)

    assert worst == (Decimal("2.50") * 100_000 + Decimal("10.00") * 16_000) / 1_000_000


def test_guard_raises_before_a_call_that_would_cross_the_cap() -> None:
    m = _meter()
    m.add(SONNET, meter.Usage(input_tokens=0, output_tokens=490_000, cache_write=0, cache_read=0))
    assert m.spent == Decimal("4.9")

    with pytest.raises(CostCapReached):
        m.guard(SONNET, prompt_tokens=20_000, max_tokens=16_000)  # worst $0.21


def test_guard_passes_when_the_worst_case_fits() -> None:
    m = _meter()

    m.guard(SONNET, prompt_tokens=20_000, max_tokens=16_000)

    assert m.spent == Decimal(0)


def test_add_accumulates_and_returns_the_call_cost() -> None:
    m = _meter()
    usage = meter.Usage(input_tokens=1_000, output_tokens=500, cache_write=0, cache_read=0)

    first = m.add(SONNET, usage)
    m.add(HAIKU, usage)

    assert first == Decimal("0.007")
    assert m.spent == Decimal("0.007") + Decimal("0.00035")
    assert m.by_model == {SONNET: Decimal("0.007"), HAIKU: Decimal("0.00035")}


def test_unpriced_model_is_refused() -> None:
    with pytest.raises(KeyError, match="no price"):
        _meter().cost("claude-unknown", meter.Usage(1, 1, 0, 0))
