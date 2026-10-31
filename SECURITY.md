# Security and privacy

## Never commit

- `data/` account, page, deck or native WebView databases;
- cookies, DMM launch tuples, access tokens, one-time tokens or viewer IDs;
- saved account exports, logs, crash dumps or browser caches;
- preserved API responses containing real `user*` state;
- game assets or extracted master data.

## Local-only design

The page server is intended to bind to loopback and accepts loopback host and
origin names only. Do not expose ports `18865`, `18866` or `9333` to an
untrusted network.

## Reporting

If you find an accidentally committed credential or personal account value,
open a private security report rather than posting the value in a public issue.
