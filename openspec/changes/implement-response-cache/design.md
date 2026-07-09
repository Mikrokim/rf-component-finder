## Context

Every adapter today calls `httpx` directly inside `search()`, on the interactive path, and each re-implements its own User-Agent, inter-request delay, and (some) retry loop. This is slow (MACOM enforces 60 s between requests; Marki/Microchip fan out to dozens–hundreds of requests) and fragile (Qorvo's ~5.3 MB page fails mid-transfer with `Server disconnected`). The source data changes on the order of weeks.

The `design.md` (§9.1) and the `cache.py`/`config.py` stubs sketch a response cache keyed by `(adapter, normalized_query_url)` with a TTL. This change implements it as a central **provider** that owns all network access; adapters ask it for a page by URL, and it is stored as a plain file in a local directory (see D2). The provider is **cache-first**: a search serves from the local cache and only reaches the network on a miss or when a copy is older than the TTL (**30 days**). There is no scheduled/background auto-refresh — the cache updates only as a side effect of a user request (or a manual `refresh`).

Relevant current facts the design must respect:
- Per-manufacturer politeness delays are already hard-coded per adapter as `_MIN_DELAY_SECONDS` and they matter (fetching too fast gets the client blocked/disconnected): Mini-Circuits / 3rWave / RWM = 1 s, AmcomUSA / Marki = 1.5 s, Qorvo / Guerrilla RF / VectraWave = 2 s, UMS = 3 s, Analog Devices = 5 s, MACOM = 60 s. Existing per-adapter fetch timeouts are 30–60 s. The provider inherits these exact values, so site-facing behavior is unchanged and a slow-but-valid site (Qorvo's 5.3 MB page) is given the time it needs rather than cut off early.
- RWM serves a self-signed certificate → its fetch runs with TLS verification disabled.
- Adapters fetch in several shapes: single GET (Qorvo, Mini-Circuits, MACOM, ADI JSON, 3rWave, VectraWave, Guerrilla RF, RWM JSON), a few GETs (UMS 5 pages, AmcomUSA categories, Marki pages), and many calls incl. `POST` (Microchip: MCP `POST` enumeration + physical-specs, then per-part feed `GET`, run concurrently in a thread pool).
- Adapters apply no server-side filtering (Verifier filters), so a page's content is query-independent. (Marki additionally does a conditional per-product enrichment; special handling of that is out of scope here — see Non-Goals.)

## Goals / Non-Goals

**Goals:**
- A single `ResponseCache` provider that all adapters retrieve through; no adapter opens a socket directly.
- **Cache-first search:** serve from the local cache when a page is fresh; reach the network only on a miss or past the TTL.
- **On an expired page, try to get fresh first** (fetch and wait, with a generous timeout); fall back to the stale copy only when the fetch fails, then keep retrying in the background to heal the cache for next time.
- A **manual** `refresh` CLI command to pre-warm the cache on demand (not scheduled).
- Centralize User-Agent / per-manufacturer delay / retries in the provider; remove that duplicated boilerplate from adapters.
- Keep each adapter's URLs, parsing, and ontology mapping byte-for-byte unchanged.

**Non-Goals:**
- Any **scheduled / timer-driven** refresh (weekly cron, Windows Task Scheduler, daemon on a clock). The cache updates only on a user request or a manual `refresh`.
- **Special handling of Marki's conditional Pass-2 per-product enrichment** — Marki is treated like any other adapter (its fetches ride the same cache path); the Pass-2 case is left to a later change.
- Caching the assembled `Candidate` list (a later optimization; v1 re-parses the stored page each search — milliseconds).
- The full T9 config (site list, global rate limits): only cache directory / TTL / enable are in scope.
- The free-form/LLM search path.

## Decisions

### D1 — Cache at the raw-response level, keyed by `(manufacturer, url)`
Store the raw HTTP response text per URL, and re-parse it on each search. **Alternatives:** (a) cache the assembled `Candidate` list per adapter — fastest read, but couples the cache to the internal model, needs a refresh to reflect any parser change, and doesn't map onto Microchip's hundreds of feeds; (b) hybrid (raw + candidates) — more code, two things to keep in sync. **Why raw:** it keeps the cache oblivious to the ontology, lets a parser fix take effect without re-fetching, and re-parsing is cheap (ms). Candidate-level caching stays available as a future layer on top.

### D2 — Local filesystem directory, one file per `(manufacturer, url)`
Store each response as a plain file under a local cache directory: `<cache_dir>/<manufacturer-slug>/<url-slug>__<hash8>.<ext>`. The `url-slug` is a sanitized, readable fragment of the URL and `<hash8>` is the first 8 hex chars of `sha256` over the full fetch identity (`url` + `method` + `params` + `body`), so the file is both human-browsable and collision-free (this is also how Microchip's `POST`s to one endpoint get distinct files). **Fetch timestamp is the file's `mtime`** — no separate metadata store. **Alternatives:** a database. **Why filesystem:** each URL is its own file, so parallel refresh threads never touch the same file and no locking is needed; the timestamp is free (`mtime`); every page is directly inspectable in a browser/editor; and there is no database — only stdlib `pathlib`/`os`, no new dependency. Atomic writes come from writing to a `.tmp` sibling then `os.replace`. A database would add transactional multi-key updates and "which pages are stale?" queries — neither of which this cache needs (staleness is a per-file `mtime` check).

### D3 — Provider-mediated retrieval via a module-level `fetch()` helper
Adapters call `rf_finder.cache.fetch(manufacturer, url, **opts)` in place of `httpx.get(...)`. A single provider instance is configured once per process (by the CLI) with the cache directory and config. **Alternatives:** (a) inject the provider into `search(spec, provider)` — explicit and testable but churns all 12 signatures and their tests; (b) set an attribute on each adapter before calling — implicit/ugly. **Why the module-level helper:** the only change per adapter is the fetch call site (URLs/parsing untouched) and the `search(spec)` signature is preserved. Tests configure the provider explicitly. Trade-off: a process-global; acceptable for a single-run CLI, and the provider is the natural singleton.

### D4 — Cache-first read-through, fetch-fresh-on-expiry with stale fallback
`fetch` resolves one URL against the local cache first:
- **Fresh** (age ≤ TTL): return the cached file. No network.
- **Expired** (age > TTL): attempt a live fetch and wait for it (generous timeout — the site gets the time it needs). On success, store and return the **fresh** copy. If the fetch fails (no network / error / timeout), return the **stale** cached copy, then keep retrying in the background (D8) to heal the cache for next time.
- **Missing** (no file): there is nothing to serve, so a live fetch is attempted (and waited on); on success store+return, on failure return `None` and the caller skips that source.

**Alternatives:** (a) a fully decoupled `cache_only` search + a scheduled background refresh job — rejected: it adds a scheduler/timer the team explicitly does not want, and never lets a user pull fresh data on demand; (b) serving stale immediately on expiry without trying to fetch first — rejected: the user should get *fresh* data when it's available, so we try the network first and only fall back to stale on failure. **Why this:** fresh is preferred when reachable; stale is a safety net for failure; and the cache self-heals in the background after a fallback.

### D5 — Manual `refresh` reuses each adapter's own `search()` to warm the cache
The manual `refresh` command calls `adapter.search(spec)` while forcing a live fetch + store for each URL, so every page an adapter's normal traversal reads gets fetched and stored — including Microchip's per-feed URLs. It is user-invoked only; it is never scheduled. **Alternative:** a per-adapter static URL list — brittle, misses dynamically discovered URLs (Microchip feeds).

### D6 — Per-request fetch options carried on the `fetch()` call
`fetch(manufacturer, url, *, method="GET", params=None, json=None, headers=None, verify=True, timeout=...)`. This preserves each adapter's specifics: RWM passes `verify=False`; Microchip passes `method="POST", json=<rpc body>`. For non-GET requests the method and body feed into the filename hash (D2) so distinct MCP calls to the same endpoint land in distinct files. Per-manufacturer **delay** and **timeout** are looked up from a provider table seeded with the constants above; per-request `headers` default to the shared browser UA and may be overridden.

### D8 — Background revalidate after a stale fallback, joined before the CLI exits
When an expired page's live fetch fails and the stale copy is served, the provider keeps retrying the fetch on a background daemon thread (single-flight per URL, using the same generous per-site timeout so a slow site has enough time to respond). Because the tool is a **short-lived CLI** — it prints results and exits — a background thread would be killed mid-fetch and never update the cache. So `__main__` **joins the outstanding revalidate threads after displaying results, before the process exits**, bounded by a max wait so a dead site can't keep the process alive indefinitely. The user sees results immediately (with the stale copy); the process then lingers briefly to let the cache heal. If it does not finish within the bound, the next search retries (the page is still expired).

## Risks / Trade-offs

- **A slow/flaky fetch on the interactive path** → an expired or missing page does pay a live fetch on the interactive path (the user waits, with a generous timeout). An expired page falls back to the stale copy on failure so the user still gets a result; only a *missing* page can end with nothing (skipped). The manual `refresh` pre-warms the cache to avoid a cold first search.
- **Background revalidate in a short-lived CLI** → the process joins the revalidate threads after showing results, bounded by a max wait, so the cache updates without hanging the process on a dead site.
- **Concurrent writes** → each URL maps to its own file, so two threads never write the same path — no lock needed. A crash/interleave can't leave a half-written page because each write goes to a `.tmp` sibling and is promoted with `os.replace` (atomic on the same volume). Reads only ever open existing files.
- **Stale data looks current** → every served page carries its `mtime` age; the CLI surfaces a per-source age / "served-stale" note so an old snapshot is visible, never silent.
- **A parser change needs no re-fetch, but a *URL* change does** → if an adapter's target URL changes, the old file goes stale and a fetch writes the new one; the old file is harmless (ignored, could be pruned later).
- **Provider becomes a single choke point** → it is thin (fetch + store + delay/retry); the `enabled=false` pass-through keeps a rollback path.

## Migration Plan

1. Land `ResponseCache` + `config` (cache-first `fetch`, TTL 30 days, `enabled=true`); no adapter changes yet.
2. Migrate adapters one at a time (`httpx.get` → `cache.fetch`), starting with **Qorvo** (the motivating failure), validating each against its saved fixture so parsing is provably unchanged.
3. Wire `__main__` search to the cache-first provider; join outstanding background revalidations (bounded) after results are displayed, before exit.
4. Add the manual `refresh` command; run it once to warm the cache.
5. Rollback: set `enabled=false` (pass-through to live fetch) or revert individual adapter call sites — each is independent.

## Open Questions

- What is the max-wait bound for joining background revalidations before the CLI exits, and should the CLI print an "updating cache…" note while it waits? (Leaning: a few seconds beyond the fetch timeout, with a brief note.)
- Do we prune superseded files (old URLs), or leave the directory append-mostly given its small size? (Leaning: leave for v1.)
