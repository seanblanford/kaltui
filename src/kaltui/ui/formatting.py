"""Plain, reusable formatting; API strings never become Rich markup."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from rich.text import Text

MUTED = "#788690"
GREEN = "#8bd49c"
RED = "#e58a8a"
AMBER = "#e6c384"
UNKNOWN = "--"


def compact(value: Decimal | None) -> str:
    if value is None:
        return UNKNOWN
    for divisor, suffix in (
        (Decimal(1_000_000_000), "b"),
        (Decimal(1_000_000), "m"),
        (Decimal(1000), "k"),
    ):
        if abs(value) >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"


def cents(value: Decimal | None) -> str:
    if value is None:
        return UNKNOWN
    return f"{value * 100:.4f}".rstrip("0").rstrip(".") + "c"


def dollars(value: Decimal | None, masked: bool = False) -> str:
    return "***" if masked else UNKNOWN if value is None else f"${value:,.2f}"


def quantity(value: Decimal | None, masked: bool = False) -> str:
    return "***" if masked else compact(value)


def depth_size(value: Decimal, maximum: Decimal, color: str) -> Text:
    """An ASCII size meter, scaled independently for each bid ladder."""
    filled = max(1, int(value / maximum * 5)) if maximum else 0
    return Text(f"{compact(value):>6} {'#' * filled}{'.' * (5 - filled)}", style=color)


def change(last: Decimal | None, previous: Decimal | None) -> Text:
    if last is None or previous is None:
        return Text(UNKNOWN, style=MUTED)
    delta = (last - previous) * 100
    return Text(f"{delta:+.2f}c", style=GREEN if delta >= 0 else RED)


def local_time(value: str, *, full: bool = False) -> str:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            return UNKNOWN
        return date.astimezone().strftime("%b %d %H:%M %Z" if full else "%H:%M:%S")
    except (ValueError, TypeError):
        return UNKNOWN


def label(name: str, value: str, style: str = "") -> Text:
    line = Text(f"{name:<12}", style=MUTED)
    line.append(value, style=style)
    return line


def lines(*rows: Text | str) -> Text:
    return Text("\n").join(Text(row) if isinstance(row, str) else row for row in rows)
