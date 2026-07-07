## Why

Today every adapter fetches live from its manufacturer site on every search, inside the interactive path, calling `httpx` directly. This makes each run slow (dozens of seconds; MACOM alone enforces a 60 s inter-request delay) and fragile: Qorvo's ~5.3 MB product-list page routinely fails mid-transfer (`Server disconnected without sending a response`), and Marki/Microchip fan out to dozens–hundreds of per-part requests. A single flaky site degrades the whole run. The network-access boilerplate (User-Agent, rate-limit delay, retries) is also duplicated across all 12 adapters.

The retrieved data changes on the order of weeks, not seconds, so re-fetching per search is wasted work. The fix is a single central **response-cache provider** that owns all network access: adapters ask it for a page by URL instead of hitting the site directly, and it serves a stored copy. A scheduled weekly refresh keeps the stored copies current, out of the interactive path. The design already anticipates this (`cache.py` T10 stub: "SQLite response cache keyed by (adapter, normalized_query_url)... TTL default 7 days"; `config.py` T9 stub) — this change implements it.

## What Changes

- **New central response-cache provider** (`cache.py`, SQLite): one component that all adapters call to retrieve a source page/feed. It stores each response as a row keyed by `(manufacturer, url)`, with the raw content, a fetch timestamp, and status. Default TTL 7 days (configurable). It owns the network access, browser User-Agent, per-host rate-limit delay, and retries — de-duplicating that boilerplate out of the 12 adapters.
- **Adapters retrieve through the provider, not the site.** Each adapter replaces its direct `httpx.get(...)`/`httpx.Client` call with a `provider.fetch(manufacturer, url, mode=...)` call. The adapter's URLs, parsing, and ontology mapping are unchanged — only the source of the bytes changes (provider instead of live socket).
- **Two provider modes decouple search from fetching:**
  - `cache_only` (interactive **search**): returns the stored page and **never touches the network**; if a page has no stored copy, retrieval yields nothing and that source is skipped. Search re-parses the stored page (fast — milliseconds).
  - `refresh` (weekly **job**): fetches live from the site, stores the fresh copy, and on failure **keeps the last good copy** (serve-stale).
- **Weekly refresh job** decoupled from search: a `refresh` CLI subcommand (`python -m rf_finder refresh [--adapter NAME] [--force]`) drives every adapter's retrieval in `refresh` mode with retries. Intended to run from a weekly **Windows Task Scheduler** entry (set up as part of rollout).
- **Serve-stale on failure.** If a refresh fetch fails (e.g. Qorvo disconnect), the previously stored page is retained and kept serving rather than erroring the run.
- **Lazy-refresh fallback.** On search, a page older than the TTL is still served immediately and a background refresh is triggered for next time; a page with no stored copy is skipped with a clear note. This self-heals even if the scheduled task never runs.
- **Cache-scoped config** (`config.py`, minimal slice of T9): cache DB path, TTL, and enable/disable, loaded from an optional `config.yaml` with committed defaults. (Full site-list/rate-limit config remains future work.)

## Capabilities

### New Capabilities
- `response-cache`: The central provider and its lifecycle — the `fetch(manufacturer, url, mode)` contract, SQLite storage keyed by `(manufacturer, url)` with content/timestamp/status, the `cache_only` vs `refresh` modes, per-host rate-limiting and retries owned by the provider, serve-stale-on-failure, lazy-refresh on stale/missing pages, the `refresh` CLI command, and the cache-scoped config (DB path, TTL, enable/disable).

### Modified Capabilities
- `manufacturer-adapters`: Adapters no longer access the network directly. Every adapter retrieves its source document(s) through the shared response-cache provider (`provider.fetch`), and the per-adapter inter-request delay / retry / User-Agent behavior is now provided centrally rather than implemented in each adapter. Adapter URLs, parsing, and ontology mapping are unchanged.

## Impact

- **New code:** `rf_finder/cache.py` (the response-cache provider), `rf_finder/config.py` (cache config), a `refresh` command in `rf_finder/__main__.py`.
- **Adapters:** every adapter's fetch call site changes from `httpx.get(...)` to `provider.fetch(...)`; the duplicated rate-limit/retry code is removed in favor of the provider's. URLs/parsing/mapping untouched. Microchip's multi-hop MCP `POST`s also route through the provider (keyed by URL + a stable body hash — confirm in design).
- **Search orchestration:** `__main__.py` runs adapters with the provider in `cache_only` mode; the `refresh` command runs them in `refresh` mode.
- **Dependencies:** SQLite via the stdlib `sqlite3` (no new dependency); optional `pyyaml` for `config.yaml` — confirm in design.
- **Ops:** a weekly Windows Task Scheduler entry to run `python -m rf_finder refresh`; a `config.example.yaml` committed.
- **Tests:** provider round-trip (fetch/store/TTL), `cache_only` never hits the network, `refresh` serve-stale on failure, per-host rate-limit honored, and each adapter parses correctly from a provider-served fixture page.
- **Out of scope:** caching the assembled `Candidate` list (a possible later optimization on top of the response cache); the full T9 config (site list, rate limits); the free-form/LLM search path.
