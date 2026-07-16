## Why

Today every adapter fetches live from its manufacturer site on every search, inside the interactive path, calling `httpx` directly. This makes each run slow (dozens of seconds; MACOM alone enforces a 60 s inter-request delay) and fragile: Qorvo's ~5.3 MB product-list page routinely fails mid-transfer (`Server disconnected without sending a response`), and Marki/Microchip fan out to dozens–hundreds of per-part requests. A single flaky site degrades the whole run. The network-access boilerplate (User-Agent, rate-limit delay, retries) is also duplicated across all 12 adapters.

The retrieved data changes on the order of weeks, not seconds, so re-fetching per search is wasted work. The fix is a central **HTTP service** that owns all network access — adapters ask it for a page by URL instead of hitting the site directly — composed over a separate **storage layer** that persists responses to disk. It is **cache-first** — a fresh local copy is served without touching the network, and the site is reached only on a miss or once a copy is older than the TTL (30 days). The design already anticipates a response cache (`cache.py` T10 stub; `config.py` T9 stub) — this change implements it as two layers (`http.py` service + `cache.py` storage), storing responses as plain files in a local directory (see design D2/D3).

## What Changes

- **New HTTP service (`http.py`) over a storage layer (`cache.py`, local files).** The service is the one component all adapters call to retrieve a source page/feed; it owns the network access, browser User-Agent, per-manufacturer rate-limit delay, and retries — de-duplicating that boilerplate out of the 12 adapters. The storage layer persists each response as a plain file under a local cache directory, one file per `(manufacturer, url)`; the file's `mtime` is its fetch timestamp. Default TTL 30 days (configurable).
- **Adapters retrieve through the HTTP service, not the site.** Each adapter replaces its direct `httpx.get(...)`/`httpx.Client` call with an `http.fetch(manufacturer, url, ...)` call, oblivious to caching. The adapter's URLs, parsing, and ontology mapping are unchanged — only the source of the bytes changes.
- **Cache-first behavior** on each page request:
  - **Fresh** (≤ TTL): served from the local cache, no network.
  - **Expired** (> TTL): the HTTP service tries a live fetch first and waits for it (generous per-site timeout) so the user gets *fresh* data; on failure it falls back to the **stale** copy and keeps retrying in the background to heal the cache for next time.
  - **Missing** (no copy): a live fetch is attempted and waited on; on failure the source is skipped.
- **Manual `refresh` command** (`python -m rf_finder refresh [--adapter NAME]`) to pre-warm the cache on demand — user-invoked, **never scheduled**. There is no timer/cron/Task Scheduler job; the cache only updates from a user request or this command.
- **Background revalidate, joined before exit.** After a stale fallback, the background retry runs on a daemon thread; because this is a short-lived CLI, `__main__` waits (bounded) for those threads after displaying results so the cache actually heals.
- **Cache-scoped config** (`config.py`, minimal slice of T9): cache directory path, TTL, and enable/disable, loaded from an optional `config.yaml` with committed defaults. (Full site-list/rate-limit config remains future work.)

## Capabilities

### New Capabilities
- `response-cache`: The HTTP service (over a storage layer) and its lifecycle — the `fetch(manufacturer, url, ...)` contract, filesystem storage under a local directory (one file per `(manufacturer, url)`, `mtime` as timestamp), the cache-first resolution (fresh served locally; expired fetched-fresh with stale-on-failure fallback + background revalidate; missing fetched or skipped), per-manufacturer rate-limiting and retries owned by the HTTP service, the manual `refresh` command, and the cache-scoped config (cache directory, TTL, enable/disable).

### Modified Capabilities
- `manufacturer-adapters`: Adapters no longer access the network directly. Every adapter retrieves its source document(s) through the shared HTTP service (`http.fetch`), and the per-adapter inter-request delay / retry / User-Agent behavior is now provided centrally rather than implemented in each adapter. Adapter URLs, parsing, and ontology mapping are unchanged.

## Impact

- **New code:** `rf_finder/http.py` (the HTTP service), `rf_finder/cache.py` (the storage layer), `rf_finder/config.py` (cache config), a `refresh` command in `rf_finder/__main__.py`.
- **Adapters:** every adapter's fetch call site changes from `httpx.get(...)` to `http.fetch(...)`; the duplicated rate-limit/retry code is removed in favor of the service's. URLs/parsing/mapping untouched. Microchip's multi-hop MCP `POST`s also route through the HTTP service (each POST body lands in its own file via the filename hash — see design D2/D6).
- **Search orchestration:** `__main__.py` resolves every source cache-first, and joins any outstanding background revalidations (bounded) after results are displayed, before exit. The manual `refresh` forces a live fetch + store for each URL.
- **Dependencies:** no database — plain files via the stdlib `pathlib`/`os` (no new dependency); optional `pyyaml` for `config.yaml` — confirm in design.
- **Ops:** run `python -m rf_finder refresh` once (or when desired) to pre-warm the cache. No scheduled job.
- **Tests:** storage round-trip (path/age/atomic write) and HTTP-service behavior (fetch/store/TTL, fresh served without network, expired fetched-fresh with stale-on-failure fallback, missing skipped on failure, per-manufacturer rate-limit honored) tested separately, and each adapter parses correctly from a service-served fixture page.
- **Out of scope:** caching the assembled `Candidate` list (a possible later optimization); special handling of Marki's conditional Pass-2 enrichment (deferred); the full T9 config (site list, rate limits); the free-form/LLM search path.
