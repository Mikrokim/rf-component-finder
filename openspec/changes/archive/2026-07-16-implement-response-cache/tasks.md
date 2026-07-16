## 1. Cache-scoped config (`config.py`)

- [x] 1.1 Implement `load_cache_config()` returning `cache_dir` path, `ttl_days` (default 30), and `enabled` (default true); read from `config.yaml` if present, else committed defaults
- [x] 1.2 Import `pyyaml` lazily so an absent `config.yaml` needs no new dependency; clear error if the file exists but is malformed
- [x] 1.3 Commit `config.example.yaml` documenting `cache_dir` / `ttl_days` / `enabled`
- [x] 1.4 Tests: defaults when file absent; values honored when present; malformed file errors clearly

## 2. HTTP service + storage layer (`http.py` service over `cache.py` storage)

- [x] 2.1 Create the cache directory layout: `<cache_dir>/<manufacturer-slug>/<url-slug>__<hash8>.<ext>`; create the directory tree if missing; the file's `mtime` is its fetch timestamp (no separate metadata store)
- [x] 2.2 Implement path derivation: manufacturer-slug subdir + sanitized readable url-slug + `sha256(url, method, params, body)[:8]`; for non-GET / bodied requests the method+body feed the hash so POSTs to one endpoint map to distinct files
- [x] 2.3 Implement cache-first `fetch(manufacturer, url, *, method="GET", params=None, json=None, headers=None, verify=True, timeout=...)`; when config `enabled=false`, pass through to a direct live request (no read/write)
- [x] 2.4 Fresh path: when the cached file's age ≤ TTL, return its content without touching the network and with no delay
- [x] 2.5 Expired / missing path: attempt a live fetch and wait for it — on success store fresh + return; on failure, return the stale copy if one exists (expired) or `None` if none exists (missing)
- [x] 2.6 Live-fetch internals: shared browser User-Agent, per-manufacturer minimum delay + generous per-site timeout seeded from the current adapter constants (delays MC/3rWave/RWM 1 s, Amcom/Marki 1.5 s, Qorvo/Guerrilla/Vectra 2 s, UMS 3 s, ADI 5 s, MACOM 60 s; timeouts 30–60 s), and transient-failure retries with backoff
- [x] 2.7 Atomic writes: write to a `.tmp` sibling then `os.replace`, so a crash/interleave never leaves a half-written file and Microchip's thread pool is safe (distinct files per URL → no lock needed)
- [x] 2.8 Staleness helper (age vs `ttl_days`) in the storage layer; module-level HTTP-service singleton + `configure(config)` used by the CLI; adapters call the module-level `http.fetch`
- [x] 2.9 Background revalidate after a stale fallback: retry the failed expired fetch on a daemon thread (single-flight per URL) and update the file on success; expose a join hook so the CLI can wait for outstanding revalidations, bounded by a max wait

## 3. Provider tests

- [x] 3.1 Round-trip: store then read returns same content; distinct URLs coexist; re-store replaces content+timestamp
- [x] 3.2 Non-GET filenames: same URL with different bodies stored in separate files
- [x] 3.3 Fresh served from cache with no network call (assert via a stub transport); expired-then-success serves fresh; expired-then-failure serves the stale copy
- [x] 3.4 Missing-then-success stores+returns; missing-then-failure returns `None`
- [x] 3.5 Per-manufacturer minimum delay enforced on live fetches; no delay on a fresh cache hit
- [x] 3.6 Retry: transient-then-success returns success without surfacing the error
- [x] 3.7 Disabled cache passes through to a live fetch with no read/write
- [x] 3.8 Stale fallback starts a background revalidate (single-flight); a fresh hit starts none

## 4. CLI wiring (`__main__.py`)

- [x] 4.1 Configure the HTTP service (cache-first) for the interactive search path
- [x] 4.2 Sources that resolve to nothing are skipped with a clear note; each result source shows its snapshot age / a "served-stale" marker when a stale copy was used
- [x] 4.3 Add a manual `refresh` subcommand (argparse): `refresh [--adapter NAME]` that forces a live fetch + store for each source; never scheduled
- [x] 4.4 Drive every adapter's `search()` during refresh so all its pages are fetched and stored; per-source outcome line (refreshed / failed) with per-adapter error isolation
- [x] 4.5 Tests: fresh searches make no network call; refresh continues past one failing source and reports per-source outcome
- [x] 4.6 Join outstanding background revalidations after results are displayed and before the process exits, bounded by a max wait (with a brief "updating cache…" note)

## 5. Adapter migration (`httpx.get` → `http.fetch`)

- [x] 5.1 **Qorvo** (motivating case): replace the live GET with `http.fetch`, drop its local delay/retry constants; validate parsing against the saved fixture (candidates identical)
- [x] 5.2 Single-GET adapters: Mini-Circuits, Analog Devices (JSON), MACOM, 3rWave, VectraWave, Guerrilla RF — same migration, each validated against its fixture
- [x] 5.3 RWM: migrate its JSON GET passing `verify=False` through `fetch`; validate against fixture
- [x] 5.4 Multi-GET adapters: UMS (5 `?function=` pages), AmcomUSA (category pages) — migrate each fetch call site; validate against fixtures
- [x] 5.5 Marki: migrate its fetch call sites through `fetch` (no special handling of the conditional Pass-2 enrichment — it rides the same cache path); validate against fixtures
- [x] 5.6 Microchip: route MCP `POST` enumeration + physical-specs and per-part feed `GET` through `fetch` (POST body in the filename hash), keeping the thread pool; validate against feed fixtures
- [x] 5.7 Remove now-dead per-adapter `_MIN_DELAY_SECONDS` / retry code; confirm the full test suite passes with parsing unchanged

## 6. Rollout / ops

- [x] 6.1 Warm the cache with one `python -m rf_finder refresh`; confirm a subsequent fresh search reads from the cache (no network) and returns fast
- [x] 6.2 Update `openspec/specs` via the archive flow once implemented and verified
