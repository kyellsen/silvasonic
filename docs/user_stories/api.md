# User Stories — API

> **Service:** API · **Tier:** 1
>
> **Status:** TO-BE. Describes the [Station API](../api/index.md) ([ADR-0032](../adr/0032-api-first-station-contract.md), *Proposed*) from the view of those who build on it. What a person does in the dashboard is in the [Dashboard stories](dashboard.md).

---

<a id="us-api01"></a>
## US-API01: Build on a contract that holds 📜

> **As a developer** of a dashboard, an integration or the fleet server
> **I want** a documented API that changes only by addition,
> **so that** what I build keeps working when the station is updated.

### Acceptance Criteria

- [ ] Every operation, field and error of the station is described in one OpenAPI document that ships with the software.
- [ ] A station states which version of the contract it implements and which optional features it has.
- [ ] Within a major version nothing is removed or renamed; an operation that will go announces it in its responses beforehand.
- [ ] A change that breaks the contract cannot be merged unnoticed.
- [ ] An error tells a program what went wrong by a stable code, and a person by a sentence.

### References

- [ADR-0032: API-First Station Contract](../adr/0032-api-first-station-contract.md)
- Contract: `getInfo`

---

<a id="us-api02"></a>
## US-API02: Connect another program 🔌

> **As a user** who runs a home-automation system or writes scripts
> **I want to** give a program its own access to my station,
> **so that** it can read detections or switch a microphone without knowing my password.

### Acceptance Criteria

- [ ] I create a token with a name, a role and an optional expiry; its secret is shown once.
- [ ] A token can do no more than the role I gave it, and never more than I can.
- [ ] I see when a token was last used and revoke it at once.
- [ ] A program follows new detections and alerts as they happen, and catches up after a lost connection.
- [ ] Too many requests are answered with how long to wait, not with a failure of the station.

### References

- [ADR-0034: Authentication and Authorization](../adr/0034-authentication-and-authorization.md)
- Contract: `createApiToken`, `revokeApiToken`, `streamEvents`, `listDetections`

---

<a id="us-api03"></a>
## US-API03: Manage many stations with the same vocabulary 🛰️

> **As an operator** of many stations
> **I want** every station to speak the same API with identifiers that never collide,
> **so that** one server can collect, show and steer them all.

### Acceptance Criteria

- [ ] Every station, recording and detection has an identifier that is unique across all stations.
- [ ] A recording says whether the station's clock was synchronised when it was made.
- [ ] Two parties changing the same setting cannot overwrite each other unnoticed.
- [ ] A station reports its health, version and pending update in a form a server can aggregate.
- [ ] What the fleet changed on a station is in that station's audit log, marked as the fleet's doing.

### Non-Functional Requirements

- A station is never required to accept incoming connections from the internet; it reaches out.

### References

- [ADR-0033: Unified Naming and Global Identifiers](../adr/0033-unified-naming-and-global-identifiers.md)
- Contract: `getStation`, `getStationStatus`, `getUpdateStatus`, `updateSettingsSection`, `listAuditLog`
