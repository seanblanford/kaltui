"""Real Textual keyboard flows with offline, synthetic readers."""

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest
from textual.widgets import DataTable, Input, Static

from kaltui.demo import DemoClient
from kaltui.errors import APIError
from kaltui.models import Page
from kaltui.settings import Settings
from kaltui.ui.app import KaltuiApp
from kaltui.ui.widgets import InfoScreen


async def settled(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def app_for(client=None, settings=None, **kwargs):
    return KaltuiApp(client or DemoClient(), settings or Settings(), demo=True, **kwargs)


async def test_demo_populates_all_panels_and_keyboard_navigation():
    app = app_for()
    async with app.run_test(size=(160, 48)) as pilot:
        await settled(app, pilot)
        assert app.query_one("#markets", DataTable).row_count == 12
        assert app.query_one("#positions", DataTable).row_count == 4
        assert app.query_one("#book", DataTable).row_count == 8
        first = app.selected
        await pilot.press("j")
        await settled(app, pilot)
        assert app.selected != first
        assert app.detail.market.ticker == app.selected
        await pilot.press("enter")
        assert isinstance(app.screen, InfoScreen)
        assert "SYNTHETIC" in str(app.screen.content)
        await pilot.press("escape")


async def test_privacy_starts_masked_and_masks_an_open_account_modal():
    app = app_for()
    async with app.run_test(size=(150, 44)) as pilot:
        await settled(app, pilot)
        table = app.query_one("#positions", DataTable)
        assert table.get_row_at(0)[2:] == ["***", "***", "***"]
        await pilot.press("m")
        assert table.get_row_at(0)[2] == "100"
        table.focus()
        await pilot.press("enter")
        assert app.screen.financial
        assert "$42.50" in str(app.screen.content)
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert not isinstance(app.screen, InfoScreen)
        assert app.masked
        assert table.get_row_at(0)[2:] == ["***", "***", "***"]


async def test_filter_consumes_shortcut_characters_and_escape_restores_rows():
    app = app_for()
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        await pilot.press("/")
        assert isinstance(app.focused, Input)
        await pilot.press("f", "e", "d")
        assert len(app.visible_markets) == 1
        assert not app.favorites_only
        await pilot.press("escape")
        assert len(app.visible_markets) == 12
        assert app.focused.id == "markets"


async def test_local_watchlist_survives_restart_and_empty_watchlist_works(tmp_path):
    path = tmp_path / "settings.json"
    app = app_for(settings_file=path)
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        selected = app.selected
        await pilot.press("w", "f")
        await settled(app, pilot)
        assert list(app.markets) == [selected]
        assert Settings.load(path).favorites == [selected]
        await pilot.press("w")
        await settled(app, pilot)
        assert not app.markets
        assert app.detail is None
        await pilot.press("r")
        await settled(app, pilot)
        assert not app.stale
        assert not app.markets


async def test_background_refresh_while_help_is_open():
    app = app_for()
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        await pilot.press("?")
        assert isinstance(app.screen, InfoScreen)
        app.refresh_data()
        await settled(app, pilot)
        assert app.detail is not None
        assert isinstance(app.screen, InfoScreen)
        await pilot.press("escape")


class FailingClient(DemoClient):
    fail = False

    async def markets(self, **kwargs):
        if self.fail:
            raise APIError("Synthetic network failure")
        return await super().markets(**kwargs)


async def test_failed_refresh_preserves_last_snapshot_with_stale_notice():
    client = FailingClient()
    app = app_for(client)
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        original = dict(app.markets)
        client.fail = True
        await pilot.press("r")
        await settled(app, pilot)
        assert app.markets == original
        assert app.stale
        assert "STALE" in str(app.query_one("#status", Static).render())
        client.fail = False
        await pilot.press("r")
        await settled(app, pilot)
        assert not app.stale


class PagedClient(DemoClient):
    calls = []

    def __init__(self):
        super().__init__()
        self.calls = []

    async def markets(self, *, cursor="", **kwargs):
        self.calls.append(cursor)
        return Page(self.catalog[2:] if cursor else self.catalog[:2], "" if cursor else "next")


async def test_pagination_refreshes_every_loaded_page():
    client = PagedClient()
    app = app_for(client)
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        assert len(app.markets) == 2
        await pilot.press("n")
        await settled(app, pilot)
        assert len(app.markets) == 12
        assert not app.cursor
        client.calls.clear()
        await pilot.press("r")
        await settled(app, pilot)
        assert client.calls == ["", "next"]
        assert len(app.markets) == 12


class SlowDetailClient(DemoClient):
    async def detail(self, ticker):
        await asyncio.sleep(0.05)
        return await super().detail(ticker)


async def test_fast_selection_never_displays_previous_contract_book():
    app = app_for(SlowDetailClient())
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        await pilot.press("j", "j", "j")
        await settled(app, pilot)
        assert app.detail.market.ticker == app.selected


@pytest.mark.parametrize("size", [(80, 24), (60, 24), (160, 48)])
async def test_responsive_layouts_and_sorting(size):
    app = app_for()
    async with app.run_test(size=size) as pilot:
        await settled(app, pilot)
        await pilot.press("l", "s", "S", "p")
        assert app.settings.layout == "stacked"
        assert app.paused
        assert app.sort_column == "title"
        assert not app.reverse
        await pilot.press("r")
        await settled(app, pilot)
        assert app.paused  # Manual reads are allowed while automatic polling is paused.


async def test_missing_prices_sort_last_in_both_directions():
    client = DemoClient()
    client.catalog = (
        replace(client.catalog[0], last=None),
        replace(client.catalog[1], last=Decimal(0)),
    )
    app = app_for(client)
    async with app.run_test(size=(140, 40)) as pilot:
        await settled(app, pilot)
        app.sort_column = "last"
        for reverse in (False, True):
            app.reverse = reverse
            app.draw_markets()
            assert app.visible_markets[-1].last is None
            assert app.visible_markets[0].last == 0


async def test_panel_numbers_buttons_and_account_highlight():
    app = app_for()
    async with app.run_test(size=(160, 48)) as pilot:
        await settled(app, pilot)
        account = app.query_one("#account-panel")
        await pilot.click("#account-note")
        assert account.has_class("active-panel")
        assert not app.query_one("#markets-panel").has_class("active-panel")
        await pilot.press("4")
        assert not account.display
        await pilot.press("4")
        assert account.display
        await pilot.click("#account-panel-expand")
        await pilot.pause()
        assert app.expanded_panel == "account-panel"
        assert account.region.width > 150
        assert not app.query_one("#markets-panel").display
        await pilot.click("#account-panel-reset")
        await pilot.pause()
        assert app.expanded_panel is None
        assert app.query_one("#markets-panel").display
        await pilot.click("#account-panel-hide")
        assert not account.display
        await pilot.press("4")
        assert account.display
        for number in range(1, 8):
            await pilot.press(str(number))
            await pilot.press(str(number))
        assert len(app.query(".panel-action")) == 21


async def test_panel_keys_do_not_intercept_input_and_last_panel_stays_visible():
    app = app_for()
    async with app.run_test(size=(160, 48)) as pilot:
        await settled(app, pilot)
        await pilot.press("/", "4")
        assert app.query_one("#filter", Input).value == "4"
        assert app.query_one("#account-panel").display
        await pilot.press("escape")
        for number in range(1, 8):
            app.action_panel(number)
        assert len(app.hidden_panels) == 6
