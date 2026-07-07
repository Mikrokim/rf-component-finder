## Context

Every adapter today calls `httpx` directly inside `search()`, on the interactive path, and each re-implements its own User-Agent, inter-request delay, and (some) retry loop. This is slow (MACOM enforces 60 s between requests; Marki/Microchip fan out to dozens–hundreds of requests) and fragile (Qorvo's ~5.3 MB page fails mid-transfer with `Server disconnected`). The source data changes on the order of weeks.

The `design.md` (§9.1) and the `cache.py`/`config.py` stubs already anticipate a *"SQLite response cache keyed by (adapter, normalized_query_url), TTL default 7 days"*. This change implements that as a central **provider** that owns all network access; adapters ask it for a page by URL. A weekly `refresh` job populates the store out-of-band, and interactive search reads it without ever touching the network.

Relevant current facts the design must respect:
- Per-manufacturer politeness delays are already hard-coded per adapter as `_MIN_DELAY_SECONDS` and they matter (fetching too fast gets the client blocked/disconnected): Mini-Circuits / 3rWave / RWM = 1 s, AmcomUSA / Marki = 1.5 s, Qorvo / Guerrilla RF / VectraWave = 2 s, UMS = 3 s, Analog Devices = 5 s, MACOM = 60 s. The provider inherits these exact values, so site-facing behavior is unchanged. **These are the minimum *spacing between requests*, not the fetch duration:** actual retrieval also pays download time (Qorvo's 5.3 MB page takes seconds, up to a 60 s timeout), retries with backoff, and — for multi-page adapters — the delay/download once per page (UMS ×5, Microchip ×hundreds). So a full refresh of a source can take **minutes**. That cost is paid **only in `refresh` mode** (the weekly background job); interactive search runs in `cache_only` and pays none of it (milliseconds from the DB).
- RWM serves a self-signed certificate → its fetch runs with TLS verification disabled.
- Adapters fetch in several shapes: single GET (Qorvo, Mini-Circuits, MACOM, ADI JSON, 3rWave, VectraWave, Guerrilla RF, RWM JSON), a few GETs (UMS 5 pages, AmcomUSA categories, Marki pages), and many calls incl. `POST` (Microchip: MCP `POST` enumeration + physical-specs, then per-part feed `GET`, run concurrently in a thread pool).
- Adapters apply no server-side filtering (Verifier filters), so a page's content is query-independent — **except** Marki, which fetches per-product pages only when the query constrains Size/VDD/Temperature.

## Goals / Non-Goals

**Goals:**
- A single `ResponseCache` provider that all adapters retrieve through; no adapter opens a socket directly.
- Interactive search never touches the network and never fails because of a live-fetch problem.
- A `refresh` CLI command, driven weekly by Windows Task Scheduler, that repopulates the store out-of-band and serves-stale on failure.
- Centralize User-Agent / per-host delay / retries in the provider; remove that duplicated boilerplate from adapters.
- Keep each adapter's URLs, parsing, and ontology mapping byte-for-byte unchanged.

**Non-Goals:**
- Caching the assembled `Candidate` list (a later optimization; v1 re-parses the stored page each search — milliseconds).
- The full T9 config (site list, global rate limits): only cache path / TTL / enable are in scope.
- The free-form/LLM search path.
- Per-part cache eviction / size caps (the corpus is small — a dozen sites, a few hundred small feeds).

## Decisions

### D1 — Cache at the raw-response level, keyed by `(manufacturer, url)`
Store the raw HTTP response text per URL, and re-parse it on each search. **Alternatives:** (a) cache the assembled `Candidate` list per adapter — fastest read, but couples the cache to the internal model, needs a refresh to reflect any parser change, and doesn't map onto Microchip's hundreds of feeds; (b) hybrid (raw + candidates) — more code, two things to keep in sync. **Why raw:** it matches the documented design, keeps the cache oblivious to the ontology, lets a parser fix take effect without re-fetching, and re-parsing is cheap (ms). Candidate-level caching stays available as a future layer on top.

### D2 — SQLite, single file, one row per `(manufacturer, url)`
**Alternatives:** one HTML file per page. **Why SQLite:** atomic writes (a mid-refresh crash can't leave a half-written page), safe concurrent read-during-write (weekly job vs. an interactive search), no filename-escaping for URL keys, natural home for the timestamp/status metadata and for "which pages are stale?" queries, and it cleanly holds Microchip's hundreds of URL-keyed feeds. `sqlite3` is stdlib — no new dependency. Inspectability (the one file-storage win) is recoverable ad hoc by dumping a blob; not worth a second storage backend.

### D3 — Provider-mediated retrieval via a module-level `fetch()` helper
Adapters call `rf_finder.cache.fetch(manufacturer, url, **opts)` in place of `httpx.get(...)`. A single provider instance is configured once per process (by the CLI) with the active **mode** and the cache DB. **Alternatives:** (a) inject the provider into `search(spec, provider)` — explicit and testable but churns all 12 signatures and their tests; (b) set an attribute on each adapter before calling — implicit/ugly. **Why the module-level helper:** the only change per adapter is the fetch call site (URLs/parsing untouched), the `search(spec)` signature is preserved, and mode is a per-run property read consistently (including from Microchip's worker threads). Tests configure the provider explicitly. Trade-off: a process-global; acceptable for a single-run CLI, and the provider is the natural singleton.

### D4 — Two modes: `cache_only` (search) and `refresh` (job)
`cache_only` serves only from storage, at any age, and returns `None` on a miss — so search is fast and cannot be broken by a site. `refresh` fetches live, stores on success, and **serves-stale** (returns the last good copy, timestamp unchanged) on failure. **Alternative:** a single passive TTL cache that fetches inline on staleness — rejected because it puts the slow/flaky fetch back on the interactive path, exactly the Qorvo failure we're removing.

### D5 — `refresh` reuses each adapter's own `search()` to discover URLs
The refresh job calls `adapter.search(maximal_spec)` with the provider in `refresh` mode. The adapter's normal traversal *is* the URL enumerator, so every page it would ever read gets fetched and stored — including Microchip's per-feed URLs. Passing a **maximal `QuerySpec`** (constraining Size/VDD/Temperature) makes Marki run its Pass-2 enrichment during refresh, so those per-product pages are cached too; interactive Marki queries then read them from cache. No adapter logic changes for this. **Alternative:** a per-adapter static URL list — brittle, misses dynamically discovered URLs (Microchip feeds).

### D6 — Per-request fetch options carried on the `fetch()` call
`fetch(manufacturer, url, *, method="GET", params=None, json=None, headers=None, verify=True, timeout=...)`. This preserves each adapter's specifics: RWM passes `verify=False`; Microchip passes `method="POST", json=<rpc body>`. For non-GET requests the cache key is `(manufacturer, url + "#" + stable_hash(method, params, json))` so distinct MCP calls to the same endpoint don't collide. Per-host **delay** is looked up from a provider table seeded with the constants above; per-request `headers` default to the shared browser UA and may be overridden.

### D7 — Config precedence and disable switch
Cache config loads from `config.yaml` if present, else committed defaults (`cache_db=./.cache/responses.db`, `ttl_days=7`, `enabled=true`). `pyyaml` is an optional dependency; if `config.yaml` is absent we never import it, so defaults work with no new dependency. When `enabled=false`, `fetch` is a transparent pass-through to a live request in both modes (today's behavior), giving a clean escape hatch.

### D8 — Lazy background refresh is best-effort (MAY)
On a `cache_only` hit that is stale, the provider serves it immediately and *may* enqueue a background refresh for next time. v1 implements this as a fire-and-forget daemon thread (single-flight per URL); if it is dropped for simplicity, correctness is unaffected because the weekly job is the real refresh path. It is specified as MAY, not SHALL.

## Risks / Trade-offs

- **Concurrent SQLite access** → Concurrent *writes* happen only in `refresh` mode (Microchip's thread pool fetching feeds in parallel). Interactive search is **read-only**, and concurrent SQLite reads are always safe. Because refresh is a background job that is not latency-sensitive, we simply **serialize writes behind a `threading.Lock` — free here, since nothing fast depends on write throughput.** Add WAL mode (readers never block on the writer) and a `busy_timeout` as a safety net, and open the connection with `check_same_thread=False`. A fully write-after-join variant (threads fetch, one thread writes) is available if we ever want zero concurrent writes at all.
- **Stale data looks current** → every served page carries its fetched-at age; the CLI surfaces a per-source age/"served-stale" note so a week-old (or older) snapshot is visible, never silent.
- **First run / empty cache** → search skips sources with no stored page and says so; the user (or the scheduled task) runs `refresh` once to warm it. Documented in the run output, not a crash.
- **Maximal-spec refresh does Marki's full ~123-request Pass 2 weekly** → acceptable: it happens off the interactive path, once a week, rate-limited.
- **A parser change needs no re-fetch, but a *URL* change does** → if an adapter's target URL changes, the old key goes stale and a `refresh` repopulates the new key; the old row is harmless (ignored, could be pruned later).
- **Provider becomes a single choke point** → it is thin (fetch + store + delay/retry); the `enabled=false` pass-through and direct `httpx` fallback keep a rollback path.

## Migration Plan

1. Land `ResponseCache` + `config` with `enabled=true` and the mode API; no adapter changes yet (provider unused).
2. Migrate adapters one at a time (`httpx.get` → `cache.fetch`), starting with **Qorvo** (the motivating failure), validating each against its saved fixture so parsing is provably unchanged.
3. Wire `__main__` search to run in `cache_only` mode; add the `refresh` command running in `refresh` mode.
4. Warm the cache with one `refresh`, then set up the weekly Windows Task Scheduler entry.
5. Rollback: set `enabled=false` (pass-through to live fetch) or revert individual adapter call sites — each is independent.

## Open Questions

- Should the weekly cadence and Task Scheduler entry be created by a helper command (`refresh --install-schedule`) or documented manual steps? (Leaning: documented + a small setup snippet.)
- Do we prune superseded rows (old URLs, failed-only entries), or leave the store append-mostly given its small size? (Leaning: leave for v1.)
- Is the lazy background-refresh thread (D8) worth including in v1, or defer entirely to the weekly job? (Leaning: defer; keep the MAY in the spec.)
