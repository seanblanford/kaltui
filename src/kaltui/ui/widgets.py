"""Keyboard-friendly tables, clock, inspection, and help overlays."""

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static


class TerminalTable(DataTable):
    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False)]


class Clock(Static):
    def on_mount(self) -> None:
        self.tick()
        self.set_interval(1, self.tick)

    def tick(self) -> None:
        self.update(datetime.now().astimezone().strftime("%H:%M:%S %Z"))


class InfoScreen(ModalScreen):
    BINDINGS = [Binding("escape,enter,q", "dismiss", "Close")]

    def __init__(self, title: str, content: Text | str, *, financial: bool = False):
        super().__init__()
        self.heading = title
        self.content = content
        self.financial = financial

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog") as dialog:
            dialog.border_title = self.heading
            yield Static(self.content, markup=False)
            yield Static("\n[ Esc / Enter ] close", classes="muted", markup=False)


HELP = """NAVIGATION
  Tab / Shift+Tab     Move between panels and inputs
  Arrows / j / k      Navigate rows; highlight loads market details
  Enter              Inspect market rules or an account row
  /                  Filter loaded markets by title or ticker
  Esc                Clear the filter / close an overlay
  g                  Search market / ticker
  Series field       Enter a series ticker, then press Enter
                     Prefix a full market ticker with @ for exact lookup
                     Empty + Enter returns to open markets
  n                  Load the next market page
  s / S              Cycle sort column / reverse direction
  Click header       Sort by that column

WORKSPACE
  w                  Add / remove selected market from LOCAL watchlist
  f                  Switch between open markets and local watchlist
  1–7                Toggle the matching numbered panel
  ⛶ / ↺ / ×          Expand / reset size and scroll / hide panel
  a / 4              Show / hide account positions and resting orders
  m / Ctrl+h         Mask / reveal personal financial values
  l                  Toggle classic / stacked layout
  p                  Pause / resume automatic refresh
  r                  Refresh / retry (also works while paused)
  ?                  This help
  q / Ctrl+c         Quit (Ctrl+c also works inside inputs)

Single-character shortcuts are disabled while typing in inputs.
Watchlist and layout are local preferences, separate for demo and live.
Privacy starts ON every launch. Unknown values show --.
Filtering and sorting apply to loaded pages; n loads more when available.
REST snapshots may lag the exchange. No trading actions exist.
The public trade tape always displays YES prices.
Account tables cover net unsettled holdings and resting orders only.
Demo data is synthetic; live mode never falls back to demo data."""
