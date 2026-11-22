"""Small GET-only Kalshi API boundary with exact route and origin allowlists."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx

from . import __version__, parsing
from .auth import Credentials
from .errors import APIError
from .models import Account, Detail, Market, Page

ORIGIN = "https://external-api.kalshi.com"
PREFIX = "/trade-api/v2"
ROUTES = frozenset(
    {
        "/markets",
        "/markets/trades",
        "/exchange/status",
        "/portfolio/balance",
        "/portfolio/positions",
        "/portfolio/orders",
    }
)


async def read_only_guard(request: httpx.Request) -> None:
    url = request.url
    path = url.path.removeprefix(PREFIX)
    allowed = path in ROUTES
    if path.startswith("/markets/"):
        parts = path.split("/")
        allowed = allowed or (
            len(parts) in (3, 4)
            and parsing.TICKER.fullmatch(parts[2]) is not None
            and (len(parts) == 3 or parts[3] == "orderbook")
        )
    if (
        request.method != "GET"
        or url.scheme != "https"
        or url.host != "external-api.kalshi.com"
        or url.port not in (None, 443)
        or not url.path.startswith(PREFIX + "/")
        or not allowed
        or url.username
        or url.password
        or request.content
    ):
        raise APIError("Request blocked by the read-only Kalshi route allowlist.")


class KalshiClient:
    authenticated: bool

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.credentials = credentials
        self.authenticated = credentials is not None
        self.http = httpx.AsyncClient(
            base_url=ORIGIN,
            timeout=httpx.Timeout(15, connect=8),
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": f"kaltui/{__version__}"},
            event_hooks={"request": [read_only_guard]},
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self._next_request = 0.0
        self._cooldown = 0.0

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with self._lock:
            now = time.monotonic()
            if now < self._cooldown:
                raise APIError("Kalshi rate limit; waiting before retry.", self._cooldown - now)
            await asyncio.sleep(max(0, self._next_request - now))
            headers = {}
            if path.startswith("/portfolio/"):
                if self.credentials is None:
                    raise APIError("Account reads require a Kalshi API key.")
                headers = self.credentials.headers(PREFIX + path)
            try:
                response = await self.http.get(PREFIX + path, params=params, headers=headers)
            except httpx.HTTPError:
                raise APIError(
                    "Cannot reach Kalshi. Check your connection; press r to retry."
                ) from None
            finally:
                self._next_request = time.monotonic() + 0.15
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "60"))
                if not 1 <= delay <= 3600:
                    delay = 60
            except ValueError:
                delay = 60
            self._cooldown = time.monotonic() + delay
            raise APIError("Kalshi rate limit; backing off before retry.", delay)
        if response.status_code in (401, 403):
            raise APIError("Kalshi denied this read. Check your API key, scopes, and system clock.")
        if response.status_code == 404:
            raise APIError("Kalshi could not find this market.")
        if response.status_code != 200:
            raise APIError(f"Kalshi returned HTTP {response.status_code}; press r to retry.")
        try:
            data = response.json()
        except ValueError:
            raise APIError("Kalshi returned invalid JSON.") from None
        if not isinstance(data, dict):
            raise APIError("Kalshi response has an unexpected format.")
        return data

    @staticmethod
    def _page(data: dict, key: str, parse: Callable) -> Page:
        rows = data.get(key)
        cursor = data.get("cursor", "")
        if (
            not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or not isinstance(cursor, str)
        ):
            raise APIError(f"Kalshi {key} response has an unexpected format.")
        return Page(tuple(parse(row) for row in rows), cursor)

    async def markets(
        self, *, cursor: str = "", series: str = "", tickers: tuple[str, ...] = ()
    ) -> Page[Market]:
        params = {"limit": 200, "status": "open", "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        if series:
            params["series_ticker"] = parsing.ticker(series)
        if tickers:
            params = {"tickers": ",".join(parsing.ticker(item) for item in tickers)}
        return self._page(await self._get("/markets", params), "markets", parsing.market)

    async def detail(self, ticker: str) -> Detail:
        path = f"/markets/{parsing.ticker(ticker)}"
        data = await self._get(path)
        if not isinstance(data.get("market"), dict):
            raise APIError("Kalshi market response has an unexpected format.")
        selected = parsing.market(data["market"])
        book, trades, notices = None, (), []
        try:
            book = parsing.orderbook(await self._get(path + "/orderbook", {"depth": 8}))
        except APIError as exc:
            notices.append(f"Order book unavailable: {exc}")
        try:
            trades = self._page(
                await self._get("/markets/trades", {"ticker": ticker, "limit": 16}),
                "trades",
                parsing.trade,
            ).items
        except APIError as exc:
            notices.append(f"Trade tape unavailable: {exc}")
        return Detail(selected, book, trades, tuple(notices))

    async def account(self) -> Account:
        results, notices = [], []
        for path, key, parser in (
            ("balance", "", parsing.balance),
            ("positions", "market_positions", parsing.position),
            ("orders", "orders", parsing.order),
        ):
            try:
                params = None if path == "balance" else {"limit": 200}
                if path == "positions":
                    params["count_filter"] = "position"
                if path == "orders":
                    params["status"] = "resting"
                data = await self._get(f"/portfolio/{path}", params)
                results.append(self._page(data, key, parser) if key else parser(data))
            except APIError as exc:
                results.append(None)
                notices.append(f"{path}: {exc}")
        return Account(*results, tuple(notices))
