"""Exercise the read-only boundary against a mock HTTP transport."""

import base64

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from kaltui.auth import Credentials
from kaltui.client import ORIGIN, PREFIX, KalshiClient, read_only_guard
from kaltui.errors import APIError, KaltuiError


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def test_every_non_get_method_is_rejected_before_transport(method):
    called = []
    client = KalshiClient(transport=httpx.MockTransport(lambda request: called.append(request)))
    try:
        with pytest.raises(APIError, match="blocked"):
            await client.http.request(method, ORIGIN + PREFIX + "/portfolio/orders")
        assert not called
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/trade-api/v2/markets",
        "http://external-api.kalshi.com/trade-api/v2/markets",
        ORIGIN + ":444/trade-api/v2/markets",
        ORIGIN + PREFIX + "/api_keys",
        ORIGIN + PREFIX + "/portfolio/orders/order-id/cancel",
        ORIGIN + PREFIX + "/markets/ABC/orderbook/delete",
        ORIGIN + "/trade-api/v20/markets",
        ORIGIN + PREFIX + "/markets/ABC%2F..%2Fapi_keys",
    ],
)
async def test_origins_and_unsupported_routes_are_rejected(url):
    with pytest.raises(APIError, match="blocked"):
        await read_only_guard(httpx.Request("GET", url))


@pytest.mark.parametrize(
    "path",
    [
        "/markets",
        "/markets/ABC-123",
        "/markets/ABC-123/orderbook",
        "/markets/trades",
        "/portfolio/balance",
        "/portfolio/orders",
        "/portfolio/positions",
    ],
)
async def test_allowlisted_reads(path):
    await read_only_guard(httpx.Request("GET", ORIGIN + PREFIX + path))


@pytest.mark.parametrize(
    "key",
    [
        ed25519.Ed25519PrivateKey.generate(),
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
    ],
)
async def test_signed_reads_and_public_requests_without_credentials(key):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/balance"):
            return httpx.Response(200, json={"balance_dollars": "12.3456", "portfolio_value": 100})
        if request.url.path.endswith("/positions"):
            return httpx.Response(200, json={"market_positions": [], "cursor": "more"})
        if request.url.path.endswith("/orders"):
            return httpx.Response(200, json={"orders": []})
        return httpx.Response(200, json={"markets": [], "cursor": "next"})

    credentials = Credentials("test-key", key)
    client = KalshiClient(credentials, transport=httpx.MockTransport(respond))
    try:
        page = await client.markets(series="KXBTC", cursor="opaque+/cursor")
        account = await client.account()
        assert page.cursor == "next"
        assert account.positions.cursor == "more"
        assert str(account.balance.cash) == "12.3456"
        assert requests[0].url.params["cursor"] == "opaque+/cursor"
        assert "KALSHI-ACCESS-KEY" not in requests[0].headers
        for request in requests[1:]:
            message = (
                request.headers["KALSHI-ACCESS-TIMESTAMP"] + "GET" + request.url.path
            ).encode()
            signature = base64.b64decode(request.headers["KALSHI-ACCESS-SIGNATURE"])
            if isinstance(key, ed25519.Ed25519PrivateKey):
                key.public_key().verify(signature, message)
            else:
                key.public_key().verify(
                    signature,
                    message,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH
                    ),
                    hashes.SHA256(),
                )
        assert "test-key" not in repr(credentials)
        with pytest.raises(KaltuiError):
            credentials.headers(PREFIX + "/api_keys")
    finally:
        await client.close()


async def test_rate_limits_back_off_without_immediate_retry():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            429, headers={"Retry-After": "120"}, json={"secret": "must not appear"}
        )

    client = KalshiClient(transport=httpx.MockTransport(respond))
    try:
        for _ in range(2):
            with pytest.raises(APIError) as error:
                await client.markets()
            assert error.value.retry_after > 0
            assert "secret" not in str(error.value)
        assert len(calls) == 1
    finally:
        await client.close()


async def test_redirects_are_not_followed_or_leaked():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/secret"})

    client = KalshiClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(APIError, match="302"):
            await client.markets()
        assert len(calls) == 1
    finally:
        await client.close()


async def test_optional_detail_failure_is_explicit():
    def respond(request):
        if request.url.path.endswith("/orderbook"):
            return httpx.Response(503)
        if request.url.path.endswith("/trades"):
            return httpx.Response(200, json={"trades": []})
        return httpx.Response(200, json={"market": {"ticker": "TEST", "title": "Example"}})

    client = KalshiClient(transport=httpx.MockTransport(respond))
    try:
        detail = await client.detail("TEST")
        assert detail.book is None
        assert "Order book unavailable" in detail.notices[0]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "body", [[], {"markets": None}, {"markets": ["bad"]}, {"markets": [], "cursor": 123}]
)
async def test_malformed_market_data_is_a_controlled_error(body):
    client = KalshiClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    )
    try:
        with pytest.raises(APIError):
            await client.markets()
    finally:
        await client.close()
