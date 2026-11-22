"""Current fixed-point API fields with explicit legacy cents fallbacks."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import APIError
from .models import Balance, Level, Market, Order, OrderBook, Position, Trade

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
TICKER = re.compile(r"[A-Za-z0-9_.:-]{1,200}\Z")


def text(value: Any, default: str = "") -> str:
    return CONTROL.sub(" ", str(value)) if value is not None else default


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and abs(result) < Decimal("1e20") else None


def value(data: dict, modern: str, legacy: str, *, cents: bool = False) -> Decimal | None:
    if modern in data:
        return number(data[modern])
    result = number(data.get(legacy))
    return result / 100 if result is not None and cents else result


def price(data: dict, name: str) -> Decimal | None:
    result = value(data, f"{name}_dollars", name, cents=True)
    return result if result is not None and 0 <= result <= 1 else None


def ticker(value: Any) -> str:
    if not isinstance(value, str) or not TICKER.fullmatch(value):
        raise APIError("Invalid market ticker; use the exact Kalshi ticker.")
    return value


def market(data: dict) -> Market:
    return Market(
        ticker=ticker(data.get("ticker")),
        title=text(data.get("title")) or text(data.get("yes_sub_title")) or data["ticker"],
        event_ticker=text(data.get("event_ticker")),
        subtitle=text(data.get("yes_sub_title")) or text(data.get("subtitle")),
        status=text(data.get("status")),
        yes_bid=price(data, "yes_bid"),
        yes_ask=price(data, "yes_ask"),
        last=price(data, "last_price"),
        previous=price(data, "previous_price"),
        volume=value(data, "volume_fp", "volume"),
        volume_24h=value(data, "volume_24h_fp", "volume_24h"),
        open_interest=value(data, "open_interest_fp", "open_interest"),
        close_time=text(data.get("close_time")),
        rules="\n\n".join(
            filter(None, (text(data.get("rules_primary")), text(data.get("rules_secondary"))))
        ),
    )


def orderbook(data: dict) -> OrderBook:
    modern = "orderbook_fp" in data
    raw = data.get("orderbook_fp" if modern else "orderbook")
    if not isinstance(raw, dict):
        raise APIError("Order book response has an unexpected format.")

    def levels(side: str) -> tuple[Level, ...]:
        key = f"{side}_dollars" if modern or f"{side}_dollars" in raw else side
        rows = raw.get(key) or []
        if not isinstance(rows, list):
            raise APIError("Order book levels have an unexpected format.")
        result = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise APIError("Order book level has an unexpected format.")
            quote, size = number(row[0]), number(row[1])
            if quote is None or size is None:
                raise APIError("Order book contains invalid numbers.")
            if not key.endswith("dollars"):
                quote /= 100
            if not 0 <= quote <= 1 or size < 0:
                raise APIError("Order book level is outside valid bounds.")
            if size:
                result.append(Level(quote, size))
        return tuple(sorted(result, key=lambda row: row.price, reverse=True))

    return OrderBook(levels("yes"), levels("no"))


def trade(data: dict) -> Trade:
    # The tape always shows the YES price, regardless of the taker's outcome.
    return Trade(
        text(data.get("taker_outcome_side") or data.get("taker_side"), "?"),
        price(data, "yes_price"),
        value(data, "count_fp", "count"),
        text(data.get("created_time")),
    )


def position(data: dict) -> Position:
    return Position(
        ticker(data.get("ticker")),
        value(data, "position_fp", "position"),
        value(data, "market_exposure_dollars", "market_exposure", cents=True),
        value(data, "realized_pnl_dollars", "realized_pnl", cents=True),
    )


def order(data: dict) -> Order:
    side = text(data.get("outcome_side") or data.get("side"), "?")
    action = text(data.get("action"))
    if not action:
        book_side = data.get("book_side")
        action = {"bid": "buy", "ask": "sell"}.get(book_side, text(book_side, "?"))
    return Order(
        ticker(data.get("ticker")),
        side,
        action,
        text(data.get("status")),
        price(data, f"{side}_price") if side in ("yes", "no") else None,
        value(data, "remaining_count_fp", "remaining_count"),
    )


def balance(data: dict) -> Balance:
    return Balance(
        value(data, "balance_dollars", "balance", cents=True),
        value(data, "portfolio_value_dollars", "portfolio_value", cents=True),
    )
