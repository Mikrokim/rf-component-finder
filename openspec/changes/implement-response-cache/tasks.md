## 1. Cache-scoped config (`config.py`)

- [ ] 1.1 Implement `load_cache_config()` returning `cache_dir` path, `ttl_days` (default 7), and `enabled` (default true); read from `config.yaml` if present, else committed defaults
- [ ] 1.2 Import `pyyaml` lazily so an absent `config.yaml` needs no new dependency; clear error if the file exists but is malformed
- [ ] 1.3 Commit `config.example.yaml` documenting `cache_dir` / `ttl_days` / `enabled`
- [ ] 1.4 Tests: defaults when file absent; values honored when present; malformed file errors clearly

## 2. Response-cache provider core (`cache.py`)

- [ ] 2.1 Create the cache directory layout: `<cache_dir>/<manufacturer-slug>/<url-slug>__<hash8>.<ext>`; create the directory tree if missing; the file's `mtime` is its fetch timestamp (no separate metadata store)
- [ ] 2.2 Implement path derivation: manufacturer-slug subdir + sanitized readable url-slug + `sha256(url, method, params, body)[:8]`; for non-GET / bodied requests the method+body feed the hash so POSTs to one endpoint map to distinct files
- [ ] 2.3 Implement `fetch(manufacturer, url, *, mode, method="GET", params=None, json=None, headers=None, verify=True, timeout=...)` dispatching on `mode`; when config `enabled=false`, pass through to a direct live request in every mode (no read/write)
- [ ] 2.4 `cache_only` path: read-only lookup, return stored content at any age, `None` on miss, never touch the network, no delay
- [ ] 2.5 `refresh` path: live fetch → store fresh + return on success; on failure keep the prior file (mtime unchanged) and return it (serve-stale); `None` when failed and no prior file
- [ ] 2.6 Live-fetch internals: shared browser User-Agent, per-manufacturer minimum delay seeded from the current adapter constants (MC/3rWave/RWM 1 s, Amcom/Marki 1.5 s, Qorvo/Guerrilla/Vectra 2 s, UMS 3 s, ADI 5 s, MACOM 60 s), and transient-failure retries with backoff
- [ ] 2.7 Atomic writes: write to a `.tmp` sibling then `os.replace`, so a crash/interleave never leaves a half-written file and Microchip's refresh-time thread pool is safe (distinct files per URL → no lock needed)
- [ ] 2.8 Staleness helper (age vs `ttl_days`); module-level provider singleton + `configure(mode, config)` used by the CLI; adapters call the module-level `fetch`
- [ ] 2.9 (Optional, MAY) fire-and-forget background refresh of a stale page on a `cache_only` hit, single-flight per key; deferrable without affecting correctness

## 3. Provider tests

- [ ] 3.1 Round-trip: store then read returns same content; distinct URLs coexist; re-store replaces content+timestamp
- [ ] 3.2 Non-GET filenames: same URL with different bodies stored in separate files
- [ ] 3.3 `cache_only`: serves stale, returns `None` on miss, makes no network call (assert via a stub transport)
- [ ] 3.4 `refresh`: stores+returns on success; serves-stale on failure with timestamp unchanged; `None` on failure with no prior
- [ ] 3.5 Per-manufacturer minimum delay enforced on live fetches; no delay on `cache_only`
- [ ] 3.6 Retry: transient-then-success returns success without surfacing the error
- [ ] 3.7 Disabled cache passes through to a live fetch with no read/write

## 4. CLI wiring (`__main__.py`)

- [ ] 4.1 Configure the provider in `cache_only` mode for the interactive search path
- [ ] 4.2 Sources whose pages are missing are skipped with a clear note; each result source shows its snapshot age / a "served-stale" marker when past TTL
- [ ] 4.3 Add a `refresh` subcommand (argparse): `refresh [--adapter NAME] [--force]`, configuring the provider in `refresh` mode
- [ ] 4.4 Build a maximal `QuerySpec` (constraining Size/VDD/Temperature) and drive every adapter's `search()` with it so all pages — incl. Marki Pass-2 — are populated; per-source outcome line (refreshed / served-stale / failed) with per-adapter error isolation
- [ ] 4.5 Tests: search runs make no network call once warm; refresh continues past one failing source and reports per-source outcome

## 5. Adapter migration (`httpx.get` → `cache.fetch`)

- [ ] 5.1 **Qorvo** (motivating case): replace the live GET with `cache.fetch`, drop its local delay/retry constants; validate parsing against the saved fixture (candidates identical)
- [ ] 5.2 Single-GET adapters: Mini-Circuits, Analog Devices (JSON), MACOM, 3rWave, VectraWave, Guerrilla RF — same migration, each validated against its fixture
- [ ] 5.3 RWM: migrate its JSON GET passing `verify=False` through `fetch`; validate against fixture
- [ ] 5.4 Multi-GET adapters: UMS (5 `?function=` pages), AmcomUSA (category pages) — migrate each fetch call site; validate against fixtures
- [ ] 5.5 Marki: migrate Pass-1 pagination and Pass-2 per-product GETs through `fetch`; confirm Pass-2 reads populated pages in `cache_only`; validate against fixtures
- [ ] 5.6 Microchip: route MCP `POST` enumeration + physical-specs and per-part feed `GET` through `fetch` (POST body in the key), keeping the thread pool; validate against feed fixtures
- [ ] 5.7 Remove now-dead per-adapter `_MIN_DELAY_SECONDS` / retry code; confirm the full test suite passes with parsing unchanged

## 6. Rollout / ops

- [ ] 6.1 Warm the cache with one `python -m rf_finder refresh`; confirm a subsequent search makes no network calls and returns fast
- [ ] 6.2 Create a weekly Windows Task Scheduler entry running `python -m rf_finder refresh`; document the setup steps (and the `--force` / single-adapter usage) in the repo
- [ ] 6.3 Update `openspec/specs` via the archive flow once implemented and verified
