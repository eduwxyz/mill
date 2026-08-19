"""Estimated cost when the provider does not charge per token.

The Claude bridge runs on a SUBSCRIPTION, so every turn comes back with
`cost.total = 0`. That is correct — on the plan, that turn generated no invoice —
but zeroing the number erases the only comparable measurement the factory has:
which ticket weighed more, which agent burns through budget, whether a criterion
became too expensive.

So when the provider does not price a turn, we estimate from the TOKENS, which do
arrive complete. The resulting number is **notional**: it is what that work would
cost on the public API, not what was charged. It is comparable across runs, which
is what it is for — and it must never be added to an invoice.

The table ages. It lives here, visible and editable, rather than hidden inside a
formula: a wrong price in a file nobody opens is worse than no price at all.
Values in USD per million tokens.
"""

from __future__ import annotations

# provider → (input, output, cache read, cache write)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus":   (15.00, 75.00, 1.50, 18.75),
    "claude-sonnet": (3.00, 15.00, 0.30, 3.75),
    "claude-haiku":  (0.80, 4.00, 0.08, 1.00),
    "claude-fable":  (3.00, 15.00, 0.30, 3.75),
}

MILLION = 1_000_000


def _table(model_id: str) -> tuple[float, float, float, float] | None:
    """`claude-sonnet-5` → the `claude-sonnet` row. Longest prefix wins."""
    target = model_id.lower()
    found = [(k, v) for k, v in PRICES.items() if target.startswith(k)]
    if not found:
        return None
    return max(found, key=lambda kv: len(kv[0]))[1]


def estimate(model_id: str, usage: dict) -> float:
    """Notional USD for one turn, from that turn's tokens.

    Returns 0.0 when the model is not in the table — inventing an average price
    would be worse than having none, because the number would enter the trace
    looking measured.
    """
    prices = _table(model_id)
    if not prices:
        return 0.0
    input_, output, cache_read, cache_write = prices
    return (
        (usage.get("input") or 0) * input_
        + (usage.get("output") or 0) * output
        + (usage.get("cacheRead") or 0) * cache_read
        + (usage.get("cacheWrite") or 0) * cache_write
    ) / MILLION
