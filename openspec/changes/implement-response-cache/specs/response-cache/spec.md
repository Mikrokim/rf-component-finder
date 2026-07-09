## ADDED Requirements

### Requirement: HTTP-service interface over a storage layer

The system SHALL provide a single **HTTP service** (the adapter-facing component) that mediates all adapter network access, composed over a separate **storage layer** that persists responses. The service SHALL expose a method `fetch(manufacturer, url, ...)` that resolves the source document for `url` cache-first and returns its text, or `None` when no document can be served. Adapters SHALL obtain source documents only through this method and SHALL NOT open network connections directly. The storage layer SHALL be responsible only for path derivation, freshness (file `mtime` vs TTL), and atomic read/write, and SHALL NOT perform network access. The HTTP service SHALL be constructed with a cache directory path and configuration, and a single instance SHALL be shared across all adapters for a given run.

#### Scenario: Fetch returns a served document

- **WHEN** `fetch(manufacturer, url)` resolves a page that can be served (from cache or a successful live fetch)
- **THEN** the document text is returned

#### Scenario: Fetch returns None when nothing can be served

- **WHEN** `fetch(manufacturer, url)` finds no cached copy and the live fetch fails
- **THEN** `None` is returned
- **AND** no exception is raised

### Requirement: Filesystem storage keyed by manufacturer and URL

The HTTP service SHALL persist responses as plain files under a local cache directory. Each stored response SHALL be a single file whose path derives from `(manufacturer, url)` — a per-manufacturer subdirectory and a filename built from a readable URL slug plus a hash of the full fetch identity — holding the raw response text; the file's modification time (`mtime`) SHALL serve as its fetch timestamp. Writing a fresh successful response for an existing `(manufacturer, url)` SHALL atomically replace that file's content (write to a temporary sibling, then replace). Distinct URLs for the same manufacturer SHALL map to distinct files and SHALL NOT overwrite one another. For non-GET requests (e.g. Microchip's MCP `POST`s), the filename hash SHALL incorporate the request method and body so that different calls to the same endpoint map to different files. The cache directory SHALL be created if it does not exist.

#### Scenario: Distinct URLs coexist for one manufacturer

- **WHEN** two different URLs are stored for the same manufacturer
- **THEN** both files exist independently
- **AND** reading either URL returns its own content

#### Scenario: Re-storing a URL replaces its content and timestamp

- **WHEN** a URL already has a stored file and a new successful response is stored for it
- **THEN** the file's content and modification time reflect the new response

#### Scenario: Same endpoint with different POST bodies stored separately

- **WHEN** two `POST` requests to the same URL carry different bodies
- **THEN** each is stored in its own file and neither overwrites the other

### Requirement: Cache-first resolution — fresh, expired, missing

The HTTP service SHALL resolve each request against the local cache first, using the file `mtime` age against the configured TTL:

- **Fresh** (age ≤ TTL): the cached file SHALL be returned and NO network request SHALL be made.
- **Expired** (age > TTL): the HTTP service SHALL attempt a live fetch and wait for it (using a generous per-site timeout so a slow-but-valid site is not cut off). On success it SHALL store and return the fresh copy. On failure it SHALL return the stale cached copy.
- **Missing** (no cached file): the HTTP service SHALL attempt a live fetch and wait for it; on success it SHALL store and return the response, and on failure it SHALL return `None`.

#### Scenario: Fresh page is served without a network request

- **WHEN** a cached page's age is within the TTL
- **THEN** the cached content is returned
- **AND** no network request is made

#### Scenario: Expired page is fetched fresh

- **WHEN** a cached page is older than the TTL and the live fetch succeeds
- **THEN** the fresh content is stored and returned
- **AND** the stored file's modification time is updated

#### Scenario: Expired page falls back to stale on fetch failure

- **WHEN** a cached page is older than the TTL and the live fetch fails
- **THEN** the stale cached content is returned
- **AND** the stored file is left unchanged

#### Scenario: Missing page is fetched, or skipped on failure

- **WHEN** no page is cached and the live fetch succeeds
- **THEN** the response is stored and returned
- **AND WHEN** no page is cached and the live fetch fails, `None` is returned

### Requirement: Background revalidate after a stale fallback

After serving a stale copy because an expired page's live fetch failed, the HTTP service SHALL keep retrying the fetch on a background thread (single-flight per URL) and update the stored file when it eventually succeeds. Because the tool is a short-lived CLI, the CLI SHALL wait for outstanding background revalidations after displaying results and before the process exits, bounded by a maximum wait so a dead site cannot hang the process. A fresh cache hit or a successful fetch SHALL NOT start a background revalidation.

#### Scenario: Stale fallback triggers a background revalidate

- **WHEN** an expired page is served stale because the live fetch failed
- **THEN** a background revalidation of that page is started
- **AND** on its success the stored file is updated

#### Scenario: Fresh hit starts no revalidation

- **WHEN** a fresh page is served from cache
- **THEN** no background revalidation is started

#### Scenario: CLI waits for revalidations before exiting

- **WHEN** background revalidations are outstanding after results are displayed
- **THEN** the process waits for them (up to the maximum wait) before exiting

### Requirement: HTTP service owns rate-limiting and retries

The HTTP service SHALL apply a browser-style User-Agent and a per-manufacturer minimum inter-request delay to all live fetches, seeded from each adapter's existing delay so site-facing behavior is unchanged, and SHALL use a generous per-site timeout so a slow-but-valid page (e.g. Qorvo's large page) is not cut off early. It SHALL retry transient failures up to a configured maximum before treating the fetch as failed. This cross-cutting behavior SHALL live in the HTTP service, so individual adapters do not implement their own delay/retry loops. Per-request options — HTTP method, query params, request body, header overrides, and TLS-verification disable (for RWM's self-signed certificate) — SHALL be honored. A fresh cache hit SHALL incur no delay.

#### Scenario: Minimum delay enforced between live fetches to a manufacturer

- **WHEN** two live fetches for the same manufacturer occur within less than its configured minimum delay
- **THEN** the HTTP service waits so that the interval between them is at least that minimum

#### Scenario: Transient failure is retried before giving up

- **WHEN** a live fetch fails transiently and then succeeds within the retry budget
- **THEN** the HTTP service returns the successful response without surfacing the transient failure

#### Scenario: Fresh cache hits incur no delay

- **WHEN** many fresh cache hits occur in succession
- **THEN** no inter-request delay is applied

### Requirement: Manual refresh command

The system SHALL provide a manual `refresh` CLI entry point (`python -m rf_finder refresh`) that forces a live fetch and store of every registered adapter's source pages. It SHALL accept an optional `--adapter NAME` to refresh a single manufacturer. It SHALL NOT be scheduled or run automatically — the cache updates only from a user page request or this command. A failure fetching one source SHALL NOT abort the whole refresh; the command SHALL continue with the remaining sources and report a per-source outcome (refreshed, failed).

#### Scenario: Refresh updates all adapters' stored pages

- **WHEN** `refresh` runs with no arguments
- **THEN** each registered adapter's source pages are fetched live and stored
- **AND** a per-adapter outcome line is reported

#### Scenario: One failing source does not abort the refresh

- **WHEN** one adapter's live fetch fails during a full refresh
- **THEN** that adapter is reported as failed
- **AND** the other adapters are still refreshed

#### Scenario: Single-adapter refresh

- **WHEN** `refresh --adapter Qorvo` runs
- **THEN** only the Qorvo source pages are refreshed

### Requirement: Cache-scoped configuration

The system SHALL load cache configuration — at least the cache directory path, the TTL (default 30 days), and an enable/disable flag — from an optional `config.yaml`, falling back to committed defaults when the file is absent. When the cache is disabled by configuration, `fetch` SHALL behave as a direct pass-through to a live fetch (no storage read or write), preserving today's behavior.

#### Scenario: Defaults apply when config file is absent

- **WHEN** no `config.yaml` is present
- **THEN** the HTTP service uses the default cache directory and a 30-day TTL

#### Scenario: Disabled cache falls back to direct fetching

- **WHEN** the cache is disabled in configuration and `fetch` is called
- **THEN** the URL is fetched live and neither stored nor read from storage
