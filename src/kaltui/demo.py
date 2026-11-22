"""Deterministic synthetic market and portfolio data; no network or key loading."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .errors import APIError
from .models import (
    Account,
    Balance,
    Detail,
    Level,
    Market,
    Order,
    OrderBook,
    Page,
    Position,
    Trade,
    utcnow,
)

DEMO_MARKETS = (
    ("FED-DEC-HOLD", "Fed holds rates in December?", "Economics", "0.72", "0.73", "0.68", 2481050),
    (
        "BTC-DEC-100K",
        "Bitcoin above $100,000 on Dec 31?",
        "Crypto",
        "0.61",
        "0.63",
        "0.64",
        1892045,
    ),
    ("CPI-NOV-3", "November CPI below 3%?", "Economics", "0.44", "0.46", "0.41", 954210),
    ("NYC-HIGH-60", "NYC high temperature above 60°F?", "Climate", "0.28", "0.30", "0.35", 182405),
    ("SPX-DEC-6500", "S&P 500 closes above 6,500?", "Financials", "0.56", "0.58", "0.52", 750320),
    ("ETH-DEC-4K", "Ethereum above $4,000 at year end?", "Crypto", "0.37", "0.39", "0.42", 481200),
    ("GDP-Q4-2", "Q4 GDP growth above 2%?", "Economics", "0.81", "0.83", "0.78", 358710),
    ("SNOW-NYC-DEC", "Snow in New York this December?", "Climate", "0.66", "0.68", "0.65", 128940),
    (
        "SPACE-LAUNCH-50",
        "More than 50 launches this quarter?",
        "Science",
        "0.87",
        "0.89",
        "0.84",
        92104,
    ),
    (
        "BOXOFFICE-100M",
        "Weekend box office above $100m?",
        "Entertainment",
        "0.23",
        "0.25",
        "0.29",
        64420,
    ),
    (
        "OIL-DEC-80",
        "Crude oil above $80 at year end?",
        "Financials",
        "0.48",
        "0.50",
        "0.46",
        228010,
    ),
    ("RAIN-SEA-FRI", "Rain in Seattle on Friday?", "Climate", "0.91", "0.93", "0.88", 42850),
)


class DemoClient:
    authenticated = True

    def __init__(self):
        self.catalog = tuple(
            Market(
                ticker=f"DEMO-{symbol}",
                title=title,
                event_ticker=f"DEMO-{category.upper()}",
                subtitle=category,
                status="active",
                yes_bid=Decimal(bid),
                yes_ask=Decimal(ask),
                last=Decimal(bid),
                previous=Decimal(previous),
                volume=Decimal(volume),
                volume_24h=Decimal(volume // 7),
                open_interest=Decimal(volume // 11),
                close_time=(utcnow() + timedelta(days=8, hours=3)).isoformat(),
                rules="SYNTHETIC DEMO MARKET. All prices, volumes, positions, and orders are fictional. This market resolves YES if the example condition is met. This is an offline demonstration, not a live Kalshi contract.",
            )
            for symbol, title, category, bid, ask, previous, volume in DEMO_MARKETS
        )

    async def close(self) -> None:
        pass

    async def markets(
        self, *, cursor: str = "", series: str = "", tickers: tuple[str, ...] = ()
    ) -> Page[Market]:
        items = self.catalog
        if tickers:
            items = tuple(item for item in items if item.ticker in tickers)
        if series:
            items = tuple(item for item in items if series.casefold() in item.ticker.casefold())
        return Page(items)

    async def detail(self, ticker: str) -> Detail:
        market = next((item for item in self.catalog if item.ticker == ticker), None)
        if market is None:
            raise APIError("Unknown demo ticker. Clear the series field to see demo markets.")
        yes = tuple(
            Level(max(Decimal(0), market.yes_bid - Decimal(i) / 100), Decimal(120 + i * 87))
            for i in range(8)
        )
        no = tuple(
            Level(max(Decimal(0), 1 - market.yes_ask - Decimal(i) / 100), Decimal(85 + i * 63))
            for i in range(8)
        )
        trades = tuple(
            Trade(
                "yes" if i % 3 else "no",
                market.last,
                Decimal(5 + i * 7),
                (utcnow() - timedelta(seconds=i * 19)).isoformat(),
            )
            for i in range(16)
        )
        return Detail(market, OrderBook(yes, no), trades)

    async def account(self) -> Account:
        return Account(
            Balance(Decimal("2450.75"), Decimal("1820.30")),
            Page(
                tuple(
                    Position(
                        item.ticker,
                        Decimal(100 if i % 2 == 0 else -60),
                        Decimal("42.50"),
                        Decimal("12.80"),
                    )
                    for i, item in enumerate(self.catalog[:4])
                )
            ),
            Page(
                tuple(
                    Order(
                        item.ticker,
                        "yes",
                        "buy",
                        "resting",
                        item.yes_bid - Decimal("0.02"),
                        Decimal(25),
                    )
                    for item in self.catalog[1:4]
                )
            ),
        )
