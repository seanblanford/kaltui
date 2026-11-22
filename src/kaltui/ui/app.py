"""Keyboard-first dashboard. Background reads keep the terminal responsive."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, Static, TabbedContent, TabPane

from ..errors import APIError
from ..models import Account, Detail, Market
from ..settings import Settings
from .formatting import (
    AMBER,
    GREEN,
    MUTED,
    RED,
    cents,
    change,
    compact,
    depth_size,
    dollars,
    label,
    lines,
    local_time,
    quantity,
)
from .panels import Panel, PanelWorkspace, ScrollPanel
from .widgets import HELP, Clock, InfoScreen, TerminalTable

SORTS = ("volume_24h", "title", "last", "spread", "close_time")


class KaltuiApp(PanelWorkspace, App):
    TITLE = "kaltui"
    CSS_PATH = "dashboard.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        *(Binding(str(n), f"panel({n})", show=False) for n in range(1, 8)),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c,ctrl+q", "quit", show=False, priority=True),
        Binding("slash", "filter", "Filter"),
        Binding("g", "lookup", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause"),
        Binding("n", "more", "Next page"),
        Binding("s", "sort", "Sort"),
        Binding("S", "reverse", show=False),
        Binding("w", "watch", "Watch"),
        Binding("f", "favorites", "Watchlist"),
        Binding("a", "account", "Account"),
        Binding("m", "privacy", "Mask"),
        Binding("ctrl+h", "privacy", show=False, priority=True),
        Binding("l", "layout", "Layout"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "clear_filter", show=False),
    ]

    def __init__(
        self,
        client,
        settings: Settings,
        *,
        settings_file: Path | None = None,
        demo: bool = False,
        series: str = "",
    ):
        super().__init__()
        self.client = client
        self.settings = settings
        self.settings_file = settings_file
        self.demo = demo
        self.series = series
        self.exact_ticker = ""
        self.markets: dict[str, Market] = {}
        self.visible_markets: list[Market] = []
        self.cursor = ""
        self.selected = ""
        self.detail: Detail | None = None
        self.account_data: Account | None = None
        self.masked = True
        self.paused = False
        self.favorites_only = False
        self.hidden_panels = set() if client.authenticated else {"account-panel"}
        self.expanded_panel = None
        self.sort_column = "volume_24h"
        self.reverse = True
        self.busy = False
        self.stale = False
        self.detail_stale = False
        self.detail_error = ""
        self.last_update: datetime | None = None
        self.last_account_at = 0.0
        self.retry_at = 0.0
        self.failures = 0
        self.notice = "Connecting to Kalshi..." if not demo else "Loading synthetic offline demo..."

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(" kaltui", id="brand")
            yield Static(
                "KALSHI TERMINAL / " + ("OFFLINE DEMO" if self.demo else "MARKET EXPLORER"),
                id="subtitle",
            )
            yield Static(" READ ONLY ", id="readonly")
            yield Clock(id="clock", markup=False)
        with Horizontal(id="toolbar"):
            yield Static(" / ", classes="toolbar-label")
            yield Input(placeholder="Filter loaded markets...", id="filter", compact=True)
            yield Static(" g ", classes="toolbar-label")
            yield Input(
                self.series,
                placeholder="Series or @market ticker + Enter",
                id="series",
                compact=True,
            )
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                with ScrollPanel(id="overview", classes="panel") as panel:
                    panel.border_title = "01 / Overview"
                    yield Static("Loading...", id="overview-text", markup=False)
                with Panel(id="watchlist-panel", classes="panel") as panel:
                    panel.border_title = "02 / Local watchlist"
                    yield Static("w to pin / f to browse", id="watch-hint", classes="muted")
                    yield TerminalTable(
                        id="watchlist", cursor_type="row", show_header=False, show_row_labels=False
                    )
            with Vertical(id="workspace"):
                with Panel(id="markets-panel", classes="panel") as panel:
                    panel.border_title = "03 / Open markets"
                    yield TerminalTable(
                        id="markets", cursor_type="row", show_row_labels=False, zebra_stripes=True
                    )
                    yield Static("Loading...", id="market-count", markup=False)
                with Panel(id="account-panel", classes="panel") as panel:
                    panel.border_title = "04 / Account [masked]"
                    with TabbedContent():
                        with TabPane("Positions", id="positions-tab"):
                            yield TerminalTable(
                                id="positions", cursor_type="row", show_row_labels=False
                            )
                        with TabPane("Resting orders", id="orders-tab"):
                            yield TerminalTable(
                                id="orders", cursor_type="row", show_row_labels=False
                            )
                    yield Static(
                        "Account data is masked on every launch.", id="account-note", markup=False
                    )
            with Vertical(id="inspector"):
                with ScrollPanel(id="contract-panel", classes="panel") as panel:
                    panel.border_title = "05 / Contract"
                    yield Static(
                        "Select a market to inspect.\nEnter opens resolution rules.",
                        id="contract",
                        markup=False,
                    )
                with Panel(id="book-panel", classes="panel") as panel:
                    panel.border_title = "06 / Order book"
                    yield Static("YES bids             NO bids", id="book-label", classes="muted")
                    yield TerminalTable(id="book", cursor_type="none", show_row_labels=False)
                    yield Static(
                        "Both sides are bids. YES ask = $1 - NO bid.", id="book-note", markup=False
                    )
                with Panel(id="tape-panel", classes="panel") as panel:
                    panel.border_title = "07 / Recent trades"
                    yield TerminalTable(id="tape", cursor_type="row", show_row_labels=False)
        yield Static("", id="status", markup=False)
        yield Footer()

    def dashboard_query(self, selector, expect_type=None):
        """Keep background updates attached to the dashboard while a modal is open."""
        return self.screen_stack[0].query_one(selector, expect_type)

    def on_mount(self) -> None:
        definitions = {
            "markets": (
                ("*", "favorite"),
                ("Market", "title"),
                ("YES", "last"),
                ("24h Δ", "change"),
                ("24h vol", "volume_24h"),
                ("Spread", "spread"),
            ),
            "watchlist": (("Ticker", "ticker"),),
            "positions": (
                ("Market", "ticker"),
                ("Side", "side"),
                ("Qty", "quantity"),
                ("Cost basis", "cost"),
                ("Realized P&L", "pnl"),
            ),
            "orders": (
                ("Market", "ticker"),
                ("Side", "side"),
                ("Action", "action"),
                ("Price", "price"),
                ("Left", "remaining"),
            ),
            "book": (
                ("YES", "yes"),
                ("Size / depth", "yes_size"),
                ("NO", "no"),
                ("Size / depth", "no_size"),
            ),
            "tape": (("Time", "time"), ("Taker", "side"), ("YES", "price"), ("Size", "quantity")),
        }
        for name, columns in definitions.items():
            table = self.dashboard_query(f"#{name}", DataTable)
            for title, key in columns:
                width = (
                    max(20, min(45, self.size.width - 115))
                    if name == "markets" and key == "title"
                    else None
                )
                table.add_column(title, key=key, width=width)
        self.apply_layout()
        self.draw_watchlist()
        self.draw_account()
        self.dashboard_query("#markets", DataTable).focus()
        self.set_interval(self.settings.poll_seconds, self.poll)
        self.refresh_data()

    async def on_unmount(self) -> None:
        await self.client.close()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 115, "narrow")
        self.set_class(event.size.width < 75, "tiny")

    def apply_layout(self) -> None:
        self.set_class(self.settings.layout == "stacked", "stacked")
        self.apply_panel_layout()

    def save(self) -> None:
        if self.settings_file is not None:
            try:
                self.settings.save(self.settings_file)
            except OSError:
                self.notify(
                    "Cannot save local preferences. Session changes still work.", severity="warning"
                )

    def poll(self) -> None:
        if not self.paused and not self.busy and time.monotonic() >= self.retry_at:
            self.refresh_data()

    @work(exclusive=True, group="catalog")
    async def refresh_data(
        self, more: bool = False, reset: bool = False, force_account: bool = False
    ) -> None:
        self.busy = True
        self.draw_status("Loading next page..." if more else "Refreshing...")
        try:
            tickers = ()
            if self.favorites_only and not self.settings.favorites:
                from ..models import Page

                page = Page(())
            else:
                tickers = (
                    tuple(self.settings.favorites)
                    if self.favorites_only
                    else ((self.exact_ticker,) if self.exact_ticker else ())
                )
                page = await self.client.markets(
                    cursor=self.cursor if more else "",
                    series="" if tickers else self.series,
                    tickers=tickers,
                )
            # Refresh every loaded page, so older pages never masquerade as fresh.
            items = {item.ticker: item for item in page.items}
            cursor = page.cursor
            if not more and not reset and len(self.markets) > len(items) and not tickers:
                seen = {cursor} if cursor else set()
                while cursor and len(items) < len(self.markets):
                    next_page = await self.client.markets(cursor=cursor, series=self.series)
                    items.update((item.ticker, item) for item in next_page.items)
                    cursor = next_page.cursor
                    if cursor in seen:
                        raise APIError(
                            "Kalshi repeated a page cursor; showing the last successful snapshot."
                        )
                    seen.add(cursor)
            if more:
                if cursor and cursor == self.cursor:
                    raise APIError("Kalshi repeated a page cursor; no additional page loaded.")
                self.markets.update(items)
            else:
                self.markets = items
            self.cursor = cursor
            self.last_update = datetime.now().astimezone()
            self.stale = False
            self.failures = 0
            self.retry_at = 0
            self.notice = (
                "Synthetic demo data / no network"
                if self.demo
                else "Public market data / REST snapshots"
            )
            self.draw_markets()
            if self.client.authenticated and (
                force_account
                or self.account_data is None
                or time.monotonic() - self.last_account_at >= 60
            ):
                self.account_data = await self.client.account()
                self.last_account_at = time.monotonic()
            self.draw_account()
            if self.selected:
                self.read_detail(self.selected, immediate=True)
        except APIError as exc:
            self.stale = True
            self.failures += 1
            self.retry_at = time.monotonic() + max(
                exc.retry_after, min(300, self.settings.poll_seconds * 2 ** min(self.failures, 4))
            )
            self.notice = str(exc)
        finally:
            self.busy = False
            self.draw_overview()
            self.draw_status()

    def draw_markets(self) -> None:
        query = self.dashboard_query("#filter", Input).value.strip().casefold()
        rows = [
            item
            for item in self.markets.values()
            if query in f"{item.ticker} {item.title} {item.subtitle}".casefold()
        ]
        known = [row for row in rows if getattr(row, self.sort_column) is not None]
        unknown = [row for row in rows if getattr(row, self.sort_column) is None]
        self.visible_markets = (
            sorted(known, key=lambda row: getattr(row, self.sort_column), reverse=self.reverse)
            + unknown
        )
        table = self.dashboard_query("#markets", DataTable)
        table.clear()
        for item in self.visible_markets:
            table.add_row(
                Text("*" if item.ticker in self.settings.favorites else " ", style=AMBER),
                Text(item.title),
                Text(cents(item.last), style=GREEN),
                change(item.last, item.previous),
                compact(item.volume_24h),
                cents(item.spread),
                key=item.ticker,
            )
        tickers = [item.ticker for item in self.visible_markets]
        if self.selected not in tickers:
            self.selected = tickers[0] if tickers else ""
            self.detail = None
            self.clear_detail()
        if self.selected:
            table.move_cursor(row=tickers.index(self.selected))
            if self.detail is None:
                self.read_detail(self.selected)
        mode = (
            "Watchlist"
            if self.favorites_only
            else "Ticker"
            if self.exact_ticker
            else self.series or "Open markets"
        )
        self.dashboard_query("#markets-panel").border_title = f"03 / {mode}"
        self.dashboard_query("#market-count", Static).update(
            f"{len(rows)} shown / {len(self.markets)} loaded  |  {self.sort_column} {'↓' if self.reverse else '↑'}  |  "
            + ("more available [n]" if self.cursor else "end of results")
        )

    @work(exclusive=True, group="detail")
    async def read_detail(self, ticker: str, immediate: bool = False) -> None:
        if not immediate:
            await asyncio.sleep(0.18)
        try:
            detail = await self.client.detail(ticker)
            if self.selected == ticker:
                self.detail = detail
                self.detail_stale = False
                self.detail_error = ""
                self.draw_detail()
        except APIError as exc:
            if self.selected == ticker:
                self.detail_stale = True
                self.detail_error = str(exc)
                if self.detail is None or self.detail.market.ticker != ticker:
                    self.clear_detail()
                    self.dashboard_query("#contract", Static).update(
                        lines(Text(ticker, style=AMBER), str(exc))
                    )
                self.dashboard_query("#contract-panel").border_title = Text("05 / Contract [STALE]")
                self.draw_status(str(exc))

    def clear_detail(self) -> None:
        self.detail_error = ""
        self.dashboard_query("#contract", Static).update(
            "Loading selected market..."
            if self.selected
            else "No matching markets.\nClear the filter, change series, or press r."
        )
        self.dashboard_query("#book", DataTable).clear()
        self.dashboard_query("#tape", DataTable).clear()
        self.dashboard_query("#contract-panel").border_title = "05 / Contract"
        self.dashboard_query("#book-note", Static).update(
            "Both sides are bids. YES ask = $1 - NO bid."
        )

    def draw_detail(self) -> None:
        detail = self.detail
        if detail is None:
            return
        item = detail.market
        self.dashboard_query("#contract-panel").border_title = Text(
            "05 / Contract" + (" [PARTIAL]" if detail.notices else "")
        )
        self.dashboard_query("#contract", Static).update(
            lines(
                Text(item.title, style="bold"),
                Text(item.ticker, style=MUTED),
                Text(item.subtitle, style=AMBER),
                "",
                label("YES bid", cents(item.yes_bid), GREEN),
                label("YES ask", cents(item.yes_ask), RED),
                label("Last", cents(item.last)),
                label("Spread", cents(item.spread)),
                label("24h volume", compact(item.volume_24h)),
                label("Open int.", compact(item.open_interest)),
                label("Status", item.status.upper()),
                label("Closes", local_time(item.close_time, full=True)),
                Text("Enter / resolution rules", style=MUTED),
            )
        )
        book = self.dashboard_query("#book", DataTable)
        book.clear()
        if detail.book is not None:
            yes, no = detail.book.yes, detail.book.no
            yes_max = max((level.quantity for level in yes), default=0)
            no_max = max((level.quantity for level in no), default=0)
            for index in range(max(len(yes), len(no))):
                a = yes[index] if index < len(yes) else None
                b = no[index] if index < len(no) else None
                book.add_row(
                    Text(cents(a.price) if a else "--", style=GREEN),
                    depth_size(a.quantity, yes_max, GREEN) if a else "--",
                    Text(cents(b.price) if b else "--", style=RED),
                    depth_size(b.quantity, no_max, RED) if b else "--",
                )
            if not yes and not no:
                self.dashboard_query("#book-note", Static).update(
                    "No resting bids in this snapshot."
                )
            else:
                ask = cents(1 - no[0].price) if no else "--"
                self.dashboard_query("#book-note", Static).update(
                    f"YES ask {ask} (implied from NO bid)\nBoth columns show bids, best first."
                )
        else:
            self.dashboard_query("#book-note", Static).update(
                "Order book unavailable; press r to retry."
            )
        tape = self.dashboard_query("#tape", DataTable)
        tape.clear()
        for trade in detail.trades:
            tape.add_row(
                local_time(trade.created_time),
                Text(trade.side.upper(), style=GREEN if trade.side == "yes" else RED),
                cents(trade.price),
                compact(trade.quantity),
            )
        self.dashboard_query("#tape-panel").border_title = "07 / Recent trades" + (
            " [empty / unavailable]" if not detail.trades else " / YES price"
        )
        self.draw_status()

    def draw_overview(self) -> None:
        balance = self.account_data.balance if self.account_data else None
        mode = "DEMO" if self.demo else "ACCOUNT" if self.client.authenticated else "PUBLIC"
        self.dashboard_query("#overview-text", Static).update(
            lines(
                Text("KALSHI / " + mode, style=f"bold {AMBER if self.demo else GREEN}"),
                "",
                label("Loaded", str(len(self.markets))),
                label("Watching", str(len(self.settings.favorites))),
                label(
                    "Refresh",
                    f"{self.settings.poll_seconds}s" + (" / PAUSED" if self.paused else ""),
                ),
                label(
                    "Updated", self.last_update.strftime("%H:%M:%S") if self.last_update else "--"
                ),
                "",
                label("Cash", dollars(balance.cash if balance else None, self.masked)),
                label("Portfolio", dollars(balance.portfolio if balance else None, self.masked)),
                "",
                Text("READ ONLY / HTTPS", style=GREEN),
                Text(
                    "m / reveal balances" if self.client.authenticated else "No API key required",
                    style=MUTED,
                ),
            )
        )

    def draw_account(self) -> None:
        positions = self.dashboard_query("#positions", DataTable)
        orders = self.dashboard_query("#orders", DataTable)
        positions.clear()
        orders.clear()
        data = self.account_data
        notes = []
        if data is not None:
            if data.positions:
                for row in data.positions.items:
                    side = (
                        "--"
                        if row.quantity is None
                        else "YES"
                        if row.quantity > 0
                        else "NO"
                        if row.quantity < 0
                        else "FLAT"
                    )
                    positions.add_row(
                        Text(row.ticker),
                        side,
                        quantity(
                            abs(row.quantity) if row.quantity is not None else None, self.masked
                        ),
                        dollars(row.cost_basis, self.masked),
                        dollars(row.realized_pnl, self.masked),
                        key=row.ticker,
                    )
                if data.positions.cursor:
                    notes.append("Positions partial (first 200)")
            if data.orders:
                for index, row in enumerate(data.orders.items):
                    orders.add_row(
                        Text(row.ticker),
                        Text(row.side.upper()),
                        Text(row.action),
                        "***" if self.masked else cents(row.price),
                        quantity(row.remaining, self.masked),
                        key=str(index),
                    )
                if data.orders.cursor:
                    notes.append("Orders partial (first 200)")
            notes.extend(data.notices)
            if not notes:
                notes.append(
                    f"{len(data.positions.items) if data.positions else 0} net holdings / {len(data.orders.items) if data.orders else 0} resting orders / {data.fetched_at.astimezone():%H:%M:%S}"
                )
        else:
            notes.append(
                "Loading account..."
                if self.client.authenticated
                else "Public mode. Set an API key to read your account; see README."
            )
        self.dashboard_query("#account-note", Static).update(" | ".join(notes))
        self.dashboard_query("#account-panel").border_title = Text(
            "04 / Account "
            + ("[masked]" if self.masked else "[visible]")
            + (
                " [PARTIAL]"
                if data
                and (
                    data.notices
                    or (data.positions and data.positions.cursor)
                    or (data.orders and data.orders.cursor)
                )
                else ""
            )
        )
        self.draw_overview()

    def draw_watchlist(self) -> None:
        table = self.dashboard_query("#watchlist", DataTable)
        table.clear()
        for symbol in self.settings.favorites:
            table.add_row(Text(symbol), key=symbol)
        self.dashboard_query("#watch-hint", Static).update(
            "w to pin / f to browse"
            if self.settings.favorites
            else "No pinned markets.\nSelect a market, then press w."
        )

    def draw_status(self, override: str = "") -> None:
        state = (
            "STALE" if self.stale else "PAUSED" if self.paused else "DEMO" if self.demo else "LIVE"
        )
        notices = [override or self.notice]
        if self.detail_error:
            notices.append("Contract STALE: " + self.detail_error)
        if self.detail and self.detail.notices:
            notices.extend(self.detail.notices)
        if self.account_data and self.account_data.notices:
            notices.append("Account reads incomplete [a]")
        status = Text(
            f" {state} ", style=f"bold {AMBER if self.stale or self.paused or self.demo else GREEN}"
        )
        status.append(" | ".join(notices), style=MUTED)
        self.dashboard_query("#status", Static).update(status)
        self.dashboard_query("#status").tooltip = "\n".join(notices)

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.draw_markets()

    @on(Input.Submitted, "#series")
    def series_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip().upper()
        self.exact_ticker = value[1:] if value.startswith("@") else ""
        self.series = "" if self.exact_ticker else value
        self.favorites_only = False
        self.reset_catalog()

    def reset_catalog(self) -> None:
        self.markets.clear()
        self.selected = ""
        self.detail = None
        self.cursor = ""
        self.draw_markets()
        self.dashboard_query("#markets", DataTable).focus()
        self.refresh_data(reset=True)

    @on(DataTable.RowHighlighted, "#markets")
    def market_highlighted(self, event: DataTable.RowHighlighted) -> None:
        selected = str(event.row_key.value)
        table = self.dashboard_query("#markets", DataTable)
        if event.cursor_row != table.cursor_row or selected not in self.markets:
            return
        if selected != self.selected:
            self.selected = selected
            self.detail = None
            self.clear_detail()
            self.read_detail(selected)

    @on(DataTable.RowSelected, "#markets")
    def market_selected(self) -> None:
        if self.detail and self.detail.market.ticker == self.selected:
            item = self.detail.market
            self.push_screen(
                InfoScreen(
                    "Resolution rules / read only",
                    lines(
                        Text(item.title, style="bold"),
                        item.ticker,
                        "",
                        item.rules or "No resolution rules supplied by Kalshi.",
                        "",
                        f"Closes: {local_time(item.close_time, full=True)}",
                    ),
                )
            )

    @on(DataTable.RowSelected, "#watchlist")
    def watch_selected(self, event: DataTable.RowSelected) -> None:
        symbol = str(event.row_key.value)
        self.exact_ticker, self.series, self.favorites_only = symbol, "", False
        self.dashboard_query("#series", Input).value = "@" + symbol
        self.reset_catalog()

    @on(DataTable.RowSelected, "#positions")
    @on(DataTable.RowSelected, "#orders")
    def account_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        values = table.get_row(event.row_key)
        content = Text("\n").join(
            Text.assemble(str(column.label), ": ", cell if isinstance(cell, Text) else str(cell))
            for column, cell in zip(table.columns.values(), values, strict=True)
        )
        self.push_screen(InfoScreen("Account row / read only", content, financial=True))

    @on(DataTable.HeaderSelected, "#markets")
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key.value
        if key in SORTS:
            self.reverse = not self.reverse if key == self.sort_column else key != "title"
            self.sort_column = key
            self.draw_markets()

    def action_filter(self) -> None:
        self.dashboard_query("#filter", Input).focus()

    def action_lookup(self) -> None:
        self.dashboard_query("#series", Input).focus()

    def action_clear_filter(self) -> None:
        self.dashboard_query("#filter", Input).value = ""
        self.dashboard_query("#markets", DataTable).focus()

    def action_refresh(self) -> None:
        self.refresh_data(force_account=True)

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.draw_overview()
        self.draw_status()
        if not self.paused:
            self.refresh_data()

    def action_more(self) -> None:
        if self.cursor and not self.busy:
            self.refresh_data(more=True)
        else:
            self.notify("Loading in progress." if self.busy else "No additional market page.")

    def action_sort(self) -> None:
        self.sort_column = SORTS[(SORTS.index(self.sort_column) + 1) % len(SORTS)]
        self.draw_markets()

    def action_reverse(self) -> None:
        self.reverse = not self.reverse
        self.draw_markets()

    def action_watch(self) -> None:
        if not self.selected:
            return
        if self.selected in self.settings.favorites:
            self.settings.favorites.remove(self.selected)
        elif len(self.settings.favorites) < 100:
            self.settings.favorites.append(self.selected)
        else:
            self.notify("The local watchlist holds up to 100 markets.")
            return
        self.save()
        self.draw_watchlist()
        self.draw_overview()
        if self.favorites_only:
            self.reset_catalog()
        else:
            self.draw_markets()

    def action_favorites(self) -> None:
        self.favorites_only = not self.favorites_only
        self.reset_catalog()

    def action_account(self) -> None:
        self.action_panel(4)

    def action_privacy(self) -> None:
        self.masked = not self.masked
        if isinstance(self.screen, InfoScreen) and self.screen.financial:
            self.screen.dismiss()
        self.draw_account()

    def action_layout(self) -> None:
        self.settings.layout = "stacked" if self.settings.layout == "classic" else "classic"
        self.apply_layout()
        self.save()

    def action_help(self) -> None:
        self.push_screen(InfoScreen("kaltui / keyboard reference", HELP))
