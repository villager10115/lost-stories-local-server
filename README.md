# Lost Stories Local Server

A local-only persistence and protocol compatibility server for a preserved
single-player client environment.

## Download a ready-to-run clean client

The public Release contains the complete client/runtime/resources in hosted
parts because GitHub limits each release asset to 2 GB. The ZIP is built
without any existing account or save database.

Run this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/villager10115/lost-stories-local-server/main/download-client.ps1 | iex
```

The script downloads all release parts, verifies SHA-256, joins them and
extracts `LostStories_Japanese/` into the current directory. No GitHub
account is required to download a public release.

The repository below remains source-only; the ready-to-run package is stored
as Release assets rather than normal Git objects.

This repository contains independently written server code, integration
tooling, tests and documentation. It does not contain the proprietary game
client, game assets, extracted master data, official account data, cookies,
tokens, saves or browser caches.

## What is included

- `stateful_server/`: FastAPI state service for account progression, gacha,
  missions, costumes, KMF management, enhancement and battles.
- `offline/`: loopback page/resource server, request proxies, validators and
  compatibility tooling.
- `launcher/`: portable service supervisor and Windows bootstrap helpers.
- `stateful_server/tests/`: focused service tests.
- `offline/test_*.js` and Python tests: page/protocol contract checks.
- `docs/`: implementation reports and design notes.
- Source-only browser overrides used by the local compatibility layer.

## Not included

The following must be supplied separately by the operator from a legally
obtained installation:

- the original client executable and Unity data;
- Addressables, media, master data and browser resources;
- test fixtures derived from game data;
- preserved page captures;
- any local account/save database.

The repository therefore is not a redistributable game package by itself.
`stateful_server/fixtures/` and the client/runtime directories are intentionally
absent.

## Account isolation

The public repository starts without a user account. It contains no formal
`state.sqlite`, `prototype.sqlite` or `decks.sqlite`, no WebView cache and no
DMM/account session material. Known local account identifiers were redacted
from the exported source.

Do not commit `data/`, `logs/`, `snapshots/`, `run/` or captured resource
directories. The included `.gitignore` blocks these paths.

## Architecture

```text
client WebView
    |
    v
offline/server.py (127.0.0.1:18865)
    |
    +-- static/resource replay
    +-- preserved WebView pages
    +-- selected API forwarding
    |
    v
stateful_server/cgls/app.py (127.0.0.1:18866)
    |
    +-- SQLite-backed local account
    +-- progression and inventory transactions
    +-- idempotent request receipts
```

Only loopback hosts are accepted. Non-loopback hosts and cross-origin writes
are rejected.

## Verification performed for the source candidate

- State service suite: `158/158`
- Offline server suite: `115/115`
- Real HTTP enhancement acceptance: `33/33` requests returned `200`
- Restart persistence and direct SQLite checks passed
- Python compilation passed
- Ports `18865`, `18866` and `9333` were closed after verification

These counts describe the development environment; tests that require
non-committed game fixtures will be skipped or cannot run until those files are
supplied.

## Development

Install Python dependencies:

```powershell
python -m pip install -r offline/requirements.txt
```

Run available tests after supplying the external resources expected by the
fixture loader:

```powershell
python -m unittest discover -s stateful_server/tests -p "test_*.py"
python -m unittest discover -s offline -p "test_*.py"
```

The package-specific verifier is
`offline/verify_enhancement_all_modules.py`. It requires an external package
root containing the client resource directories and master data.

## Legal

This is an unofficial preservation and research project. It is not affiliated
with or endorsed by the game publisher, developer, DMM or any rights holder.
Game names, trademarks, clients and assets remain the property of their
respective owners. See `NOTICE.md`.

## License

Original code in this repository is released under the MIT License. The license
does not grant rights to any third-party game client, asset, trademark or
service data.
