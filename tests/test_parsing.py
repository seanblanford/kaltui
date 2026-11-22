from decimal import Decimal

import pytest

from kaltui import parsing
from kaltui.errors import APIError
from kaltui.ui.formatting import cents, compact, dollars


def test_fixed_point_prices_and_fractional_contracts_preserve_precision():
    market = parsing.market(
        {
            "ticker": "TEST",
            "last_price_dollars": "0.123456",
            "yes_bid_dollars": "0.1230",
            "yes_ask_dollars": "0.1240",
            "volume_fp": "1234.56",
        }
    )
    assert market.last == Decimal("0.123456")
    assert market.spread == Decimal("0.0010")
    assert market.volume == Decimal("1234.56")
    assert cents(market.last) == "12.3456c"
    assert cents(Decimal(0)) == "0c"
    assert compact(Decimal(100)) == "100"
    assert dollars(None) == "--"


@pytest.mark.parametrize("invalid", [None, True, "oops", "NaN", "Infinity", "1e999"])
def test_unknown_values_are_never_fabricated_zeroes(invalid):
    assert parsing.number(invalid) is None
    market = parsing.market({"ticker": "TEST", "yes_bid_dollars": invalid, "yes_bid": 50})
    assert market.yes_bid is None
    assert market.yes_ask is None


def test_legacy_cents_and_zero_values():
    market = parsing.market({"ticker": "TEST", "yes_bid": 0, "yes_ask": 7, "volume": 100})
    assert market.yes_bid == 0
    assert market.yes_ask == Decimal("0.07")
    assert market.volume == 100
    assert parsing.balance({"balance": 200, "portfolio_value": 300}).cash == 2


def test_book_is_sorted_as_two_bid_ladders_and_fractional_sizes():
    book = parsing.orderbook(
        {
            "orderbook_fp": {
                "yes_dollars": [["0.45", "1.25"], ["0.46", "2.75"]],
                "no_dollars": [["0.53", "5.50"]],
            }
        }
    )
    assert book.yes[0].price == Decimal("0.46")
    assert book.yes[0].quantity == Decimal("2.75")
    assert 1 - book.no[0].price == Decimal("0.47")
    assert parsing.orderbook({"orderbook": {"yes": [[45, 100]], "no": None}}).yes[
        0
    ].price == Decimal("0.45")


@pytest.mark.parametrize("row", [["NaN", "1"], ["0.5", "-1"], ["2", "1"], ["0.5"], "bad"])
def test_invalid_book_levels_are_not_displayed(row):
    with pytest.raises(APIError):
        parsing.orderbook({"orderbook_fp": {"yes_dollars": [row]}})


def test_new_order_and_trade_side_fields():
    order = parsing.order(
        {
            "ticker": "TEST",
            "outcome_side": "no",
            "book_side": "bid",
            "no_price_dollars": "0.72",
            "remaining_count_fp": "2.50",
        }
    )
    assert (order.side, order.action, order.price) == ("no", "buy", Decimal("0.72"))
    trade = parsing.trade(
        {"taker_outcome_side": "no", "yes_price_dollars": "0.28", "count_fp": "2.50"}
    )
    assert (trade.side, trade.price, trade.quantity) == ("no", Decimal("0.28"), Decimal("2.50"))


def test_api_strings_cannot_inject_terminal_control_sequences():
    market = parsing.market({"ticker": "TEST", "title": "[bold]hello\x1b]52;clipboard\x07"})
    assert "\x1b" not in market.title
    assert "\x07" not in market.title
    assert "[bold]" in market.title  # Passed to Rich as Text, never interpreted as markup.
