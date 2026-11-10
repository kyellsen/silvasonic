# Station API

> **Status:** TO-BE — design draft. No service implements it yet. Decided in [ADR-0032](../adr/0032-api-first-station-contract.md) (*Proposed*).

The Station API is the one contract through which the dashboard, a fleet server and any other client read and change a station.

*   **The contract:** [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1). Its description states the conventions — naming, identifiers, time, paging, errors, concurrency, authentication, compatibility.
*   **Why it exists and what follows from it:** [ADR-0032](../adr/0032-api-first-station-contract.md).
*   **Names and identifiers:** [ADR-0033](../adr/0033-unified-naming-and-global-identifiers.md).
*   **Sessions, tokens and roles:** [ADR-0034](../adr/0034-authentication-and-authorization.md).
*   **The service that will implement it:** [API service](../services/api.md).

## Reading the draft

Each operation carries two markers:

| Marker | Values | Meaning |
| --- | --- | --- |
| `x-maturity` | `core`, `planned` | `core` is the first implementation, what the local dashboard needs. `planned` reserves the name and shape of a feature whose backend does not exist yet. |
| `x-required-role` | `public`, `viewer`, `operator`, `admin` | The lowest role the operation accepts. |

## Keeping it honest

The file is written by hand only while nothing implements it. With the `api` service it becomes generated output: the service produces the document, the repository holds a committed copy, and the gate fails when the two differ or when a change breaks compatibility with `main`.

<swagger-ui src="openapi.yaml"/>
