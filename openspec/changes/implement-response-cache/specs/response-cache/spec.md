## ADDED Requirements

### Requirement: Response-cache provider interface

The system SHALL provide a single response-cache component (the "provider") that mediates all adapter network access. It SHALL expose a method `fetch(manufacturer, url, *, mode)` that returns the source document text for `url`, or `None` when no document can be served. Adapters SHALL obtain source documents only through this method and SHALL NOT open network connections directly. The provider SHALL be constructed with a cache directory path and configuration, and a single instance SHALL be shared across all adapters for a given run.

#### Scenario: Fetch returns stored content for a known URL

- **WHEN** a page for `(manufacturer, url)` is stored and `fetch(manufacturer, url, mode=cache_only)` is called
- **THEN** the stored document text is returned
- **AND** no network request is made

#### Scenario: Fetch returns None when nothing can be served

- **WHEN** `fetch(manufacturer, url, mode=cache_only)` is called for a URL with no stored copy
- **THEN** `None` is returned
- **AND** no exception is raised

### Requirement: Filesystem storage keyed by manufacturer and URL

The provider SHALL persist responses as plain files under a local cache directory. Each stored response SHALL be a single file whose path derives from `(manufacturer, url)` — a per-manufacturer subdirectory and a filename built from a readable URL slug plus a hash of the full fetch identity — holding the raw response text; the file's modification time (`mtime`) SHALL serve as its fetch timestamp. Writing a fresh successful response for an existing `(manufacturer, url)` SHALL atomically replace that file's content (write to a temporary sibling, then replace). Distinct URLs for the same manufacturer SHALL map to distinct files and SHALL NOT overwrite one another. For non-GET requests (e.g. Microchip's MCP `POST`s), the filename hash SHALL incorporate the request method and body so that different calls to the same endpoint map to different files. The cache directory SHALL be created if it does not exist.

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

### Requirement: cache_only mode never touches the network

In `cache_only` mode the provider SHALL serve only from storage and SHALL NOT make any network request, regardless of the stored copy's age. IF a stored copy exists it SHALL be returned even when older than the TTL; IF no stored copy exists `fetch` SHALL return `None`. This is the mode used by interactive search so that a search never blocks on, or fails because of, a live fetch.

#### Scenario: Stale copy is still served in cache_only mode

- **WHEN** a stored page is older than the configured TTL and `fetch(..., mode=cache_only)` is called
- **THEN** the stale content is returned
- **AND** no network request is made

#### Scenario: Missing copy yields None, not a fetch

- **WHEN** no page is stored and `fetch(..., mode=cache_only)` is called
- **THEN** `None` is returned and no network request is made

### Requirement: refresh mode fetches live and serves stale on failure

In `refresh` mode the provider SHALL fetch the URL live from the site, and on success SHALL store the fresh response and return it. On a failed live fetch (transport error, non-success status, or empty body), the provider SHALL retain the previously stored response and return it (serve-stale) rather than raising; the stored file's modification time SHALL NOT advance on a failed refresh. IF the live fetch fails AND no previously stored response exists, `fetch` SHALL return `None` (the source is then skipped by the caller).

#### Scenario: Successful refresh stores and returns fresh content

- **WHEN** `fetch(..., mode=refresh)` succeeds against the live site
- **THEN** the fresh content is stored and returned
- **AND** the stored fetch timestamp is updated

#### Scenario: Failed refresh serves the last good copy

- **WHEN** a live fetch fails but a previously stored copy exists
- **THEN** the previously stored content is returned
- **AND** the stored fetch timestamp is unchanged

#### Scenario: Failed refresh with no prior copy returns None

- **WHEN** a live fetch fails and no copy was ever stored
- **THEN** `None` is returned and no exception propagates to abort the run

### Requirement: Provider owns rate-limiting and retries

The provider SHALL apply a browser-style User-Agent and a per-manufacturer minimum inter-request delay to all live fetches, seeded from each adapter's existing delay so site-facing behavior is unchanged, and SHALL retry transient failures up to a configured maximum before treating the fetch as failed. This cross-cutting behavior SHALL live in the provider, so individual adapters do not implement their own delay/retry loops. Rate-limiting and retries SHALL apply only to live fetches (`refresh` mode); `cache_only` reads SHALL incur no delay. Per-request options — HTTP method, query params, request body, header overrides, and TLS-verification disable (for RWM's self-signed certificate) — SHALL be honored.

#### Scenario: Minimum delay enforced between live fetches to a manufacturer

- **WHEN** two live fetches for the same manufacturer occur within less than its configured minimum delay
- **THEN** the provider waits so that the interval between them is at least that minimum

#### Scenario: Transient failure is retried before giving up

- **WHEN** a live fetch fails transiently and then succeeds within the retry budget
- **THEN** the provider returns the successful response without surfacing the transient failure

#### Scenario: cache_only reads incur no delay

- **WHEN** many `cache_only` reads occur in succession
- **THEN** no inter-request delay is applied

### Requirement: TTL and lazy refresh on stale pages

The provider SHALL treat a stored page as fresh while its age is within the configured TTL (default 7 days) and stale beyond it. During interactive search, a stale page SHALL be served immediately (never blocking the search) and MAY trigger a background refresh so the next search sees fresh data. Missing pages SHALL NOT trigger a blocking inline fetch during search; they are skipped and left to the refresh job.

#### Scenario: Stale page is served immediately during search

- **WHEN** search reads a page older than the TTL
- **THEN** the stale content is returned immediately without blocking on a live fetch

#### Scenario: Fresh page is served without any refresh

- **WHEN** search reads a page whose age is within the TTL
- **THEN** the content is returned and no refresh is initiated

### Requirement: Refresh command

The system SHALL provide a `refresh` CLI entry point (`python -m rf_finder refresh`) that drives every registered adapter's retrieval in `refresh` mode, storing fresh copies of all their source pages. It SHALL accept an optional `--adapter NAME` to refresh a single manufacturer and an optional `--force` to refresh regardless of current freshness. A failure fetching one source SHALL NOT abort the whole refresh; the command SHALL continue with the remaining sources and report a per-source outcome (refreshed, served-stale, or failed).

#### Scenario: Refresh updates all adapters' stored pages

- **WHEN** `refresh` runs with no arguments
- **THEN** each registered adapter's source pages are fetched live and stored
- **AND** a per-adapter outcome line is reported

#### Scenario: One failing source does not abort the refresh

- **WHEN** one adapter's live fetch fails during a full refresh
- **THEN** that adapter is reported as failed or served-stale
- **AND** the other adapters are still refreshed

#### Scenario: Single-adapter refresh

- **WHEN** `refresh --adapter Qorvo` runs
- **THEN** only the Qorvo source pages are refreshed

### Requirement: Cache-scoped configuration

The system SHALL load cache configuration — at least the cache directory path, the TTL, and an enable/disable flag — from an optional `config.yaml`, falling back to committed defaults when the file is absent. When the cache is disabled by configuration, `fetch` SHALL behave as a direct pass-through to a live fetch in every mode (no storage read or write), preserving today's behavior.

#### Scenario: Defaults apply when config file is absent

- **WHEN** no `config.yaml` is present
- **THEN** the provider uses the default cache path and a 7-day TTL

#### Scenario: Disabled cache falls back to direct fetching

- **WHEN** the cache is disabled in configuration and `fetch` is called
- **THEN** the URL is fetched live and neither stored nor read from storage
