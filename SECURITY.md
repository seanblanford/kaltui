# Security

The application sends only allowlisted HTTPS GET requests to
`external-api.kalshi.com`. The request guard rejects other methods, origins,
ports, request bodies, and unsupported routes before the HTTP transport runs.
Redirects are disabled. There is no order creation, modification, cancellation,
key management, or remote watchlist API in the application.

Public market reads do not carry credentials. Optional account requests are
signed in memory using an RSA or Ed25519 private key supplied by the user.
The private key itself is never transmitted. Use a key restricted to the required
read scopes where supported. Application read-only enforcement does not change
permissions attached to the key at Kalshi.

Keep private key files outside the checkout. The app reads only the explicitly
configured key path and does not load `.env` files. Do not put a credential into
a command-line argument or submit it in an issue. HTTP errors use canned messages;
server response bodies, headers, keys, account snapshots, and account identifiers
are not logged or persisted.

Account financial values start masked on each launch. Masking is a display
control: market tickers, position sides, order actions, and row counts remain
visible. Revealing values is session-only. Closing or masking an account detail
overlay clears its visible values. Local preferences contain only public market
tickers, layout, and refresh interval, saved atomically with mode `0600` on Unix.
Demo preferences use a separate file.

For public mirrors, review tracked source before enabling publication. Exclusion
patterns are not a secret scanner and cannot retract already published material.
See `docs/public-mirrors.md` in the source repository for setup.

Report vulnerabilities privately to the repository owner through the hosting
provider's private reporting channel when available. Do not post credentials,
private keys, account responses, or personal financial information in public issues.
