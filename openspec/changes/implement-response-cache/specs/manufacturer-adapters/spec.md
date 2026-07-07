## MODIFIED Requirements

### Requirement: Adapter interface

The system SHALL define an abstract `Adapter` base class with class attributes `manufacturer` (a name string) and `supported_components` (the collection of component-type names the adapter handles), and an abstract method `search(spec) -> list[Candidate]`. A subclass that does not implement `search` SHALL NOT be instantiable. The `search` method SHALL raise `AdapterError` on a retrieval failure rather than crash silently, and SHALL NOT decide matches.

Adapters SHALL NOT open network connections directly. Every source document an adapter retrieves SHALL be obtained through the shared response-cache provider (`fetch(manufacturer, url, ...)`). The per-adapter browser User-Agent, minimum inter-request delay, and transient-failure retry behavior SHALL be supplied by the provider rather than implemented in the adapter; each adapter's target URLs, HTML/JSON parsing, and ontology mapping SHALL be unchanged by this. When the provider returns no document for a URL (a cache miss in `cache_only` mode, or a failed live fetch with no stored copy), the adapter SHALL treat that source page as unavailable and skip it rather than raise.

#### Scenario: Subclass without search cannot be instantiated

- **WHEN** a subclass of `Adapter` that does not implement `search` is instantiated
- **THEN** a `TypeError` is raised

#### Scenario: Concrete adapter can be instantiated

- **WHEN** a subclass that implements `search` is instantiated
- **THEN** the instance is an `Adapter`

#### Scenario: Adapter retrieves through the provider, not the network

- **WHEN** an adapter's `search` runs and needs a source page
- **THEN** it obtains the page via the response-cache provider's `fetch`
- **AND** it does not issue a direct `httpx` network call of its own

#### Scenario: Parsing is unchanged when served from the provider

- **WHEN** an adapter parses a page served by the provider from a saved fixture
- **THEN** it produces the same candidates it produced when fetching that page live
