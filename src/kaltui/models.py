"""Read-only view models. Monetary values are Decimal dollars, never floats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Generic, TypeVar

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    cursor: str = ""


@dataclass(frozen=True)
class Market:
    ticker: str
    title: str
    event_ticker: str = ""
    subtitle: str = ""
    status: str = ""
    yes_bid: Decimal | None = None
    yes_ask: Decimal | None = None
    last: Decimal | None = None
    previous: Decimal | None = None
    volume: Decimal | None = None
    volume_24h: Decimal | None = None
    open_interest: Decimal | None = None
    close_time: str = ""
    rules: str = ""

    @property
    def spread(self) -> Decimal | None:
        if self.yes_ask is None or self.yes_bid is None:
            return None
        return self.yes_ask - self.yes_bid


@dataclass(frozen=True)
class Level:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderBook:
    yes: tuple[Level, ...] = ()
    no: tuple[Level, ...] = ()


@dataclass(frozen=True)
class Trade:
    side: str
    price: Decimal | None
    quantity: Decimal | None
    created_time: str


@dataclass(frozen=True)
class Detail:
    market: Market
    book: OrderBook | None
    trades: tuple[Trade, ...]
    notices: tuple[str, ...] = ()
    fetched_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: Decimal | None
    cost_basis: Decimal | None
    realized_pnl: Decimal | None


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str
    action: str
    status: str
    price: Decimal | None
    remaining: Decimal | None


@dataclass(frozen=True)
class Balance:
    cash: Decimal | None
    portfolio: Decimal | None


@dataclass(frozen=True)
class Account:
    balance: Balance | None
    positions: Page[Position] | None
    orders: Page[Order] | None
    notices: tuple[str, ...] = ()
    fetched_at: datetime = field(default_factory=utcnow)
