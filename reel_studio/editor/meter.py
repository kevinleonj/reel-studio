"""What an order has spent on models, and the guard that stops it crossing the cap (D37, EDITOR §8).

Prices come from config/prices.toml (per million tokens, F05) as Decimal, and nothing is rounded
inside the meter. Haiku prompts above `long_prompt_threshold_tokens` use the long tier for every
part of that call, cached tokens counting towards the prompt size.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from reel_studio.core import constants
from reel_studio.core.config import ClaudePrice, Prices
from reel_studio.core.errors import CostCapReached


@dataclass(frozen=True)
class Usage:
    """Token counts of one Claude response (anthropic `usage`)."""

    input_tokens: int
    output_tokens: int
    cache_write: int  # cache_creation_input_tokens
    cache_read: int  # cache_read_input_tokens

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write + self.cache_read


@dataclass(frozen=True)
class _Rates:
    input: Decimal
    cache_write: Decimal
    cache_read: Decimal
    output: Decimal


def _rates(price: ClaudePrice, prompt_tokens: int) -> _Rates:
    threshold = price.long_prompt_threshold_tokens
    long = threshold is not None and prompt_tokens > threshold
    if (
        long
        and price.long_input is not None
        and price.long_cache_write_5m is not None
        and price.long_cache_read is not None
        and price.long_output is not None
    ):
        return _Rates(
            price.long_input, price.long_cache_write_5m, price.long_cache_read, price.long_output
        )
    return _Rates(price.input, price.cache_write_5m, price.cache_read, price.output)


@dataclass
class Meter:
    prices: Prices
    cap: Decimal
    spent: Decimal = Decimal(0)
    by_model: dict[str, Decimal] = field(default_factory=dict)

    def _price(self, model: str) -> ClaudePrice:
        price = self.prices.claude.get(model)
        if price is None:
            raise KeyError(f"no price for {model} in config/prices.toml")
        return price

    def cost(self, model: str, usage: Usage) -> Decimal:
        """(input x in + cache_write x cw + cache_read x cr + output x out) / 1,000,000."""
        r = _rates(self._price(model), usage.prompt_tokens)
        total = (
            usage.input_tokens * r.input
            + usage.cache_write * r.cache_write
            + usage.cache_read * r.cache_read
            + usage.output_tokens * r.output
        )
        return total / constants.TOKENS_PER_PRICE_UNIT

    def worst_case(self, model: str, prompt_tokens: int, max_tokens: int) -> Decimal:
        """The whole prompt at the dearer of input and cache write (caching writes the new
        prefix), plus every allowed output token (EDITOR §8)."""
        r = _rates(self._price(model), prompt_tokens)
        dearest_in = max(r.input, r.cache_write)
        return (
            prompt_tokens * dearest_in + max_tokens * r.output
        ) / constants.TOKENS_PER_PRICE_UNIT

    def guard(self, model: str, prompt_tokens: int, max_tokens: int) -> None:
        worst = self.worst_case(model, prompt_tokens, max_tokens)
        if self.spent + worst > self.cap:
            raise CostCapReached(f"spent ${self.spent} + worst case ${worst} > cap ${self.cap}")

    def add(self, model: str, usage: Usage) -> Decimal:
        cost = self.cost(model, usage)
        self.spent += cost
        self.by_model[model] = self.by_model.get(model, Decimal(0)) + cost
        return cost
