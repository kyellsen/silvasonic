# Milestone v0.12.0 — Secure Access

> **Target:** v0.12.0 — HTTPS on every hostname, and remote access to the station through Tailscale
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0035](../../adr/0035-https-and-certificates.md), [ADR-0034](../../adr/0034-authentication-and-authorization.md), [Tailscale spec](../../services/tailscale.md), [Port Allocation](../../arch/port_allocation.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** [Gateway Stories](../../user_stories/gateway.md)

---

## Overview

Since v0.8.1 only the Gateway listens on the network, and since v0.10.0 the API authenticates every request. This milestone encrypts that path and opens a second one: the same interface, reachable from a phone or laptop anywhere through the owner's tailnet. Tailscale was planned for v1.5.0; it moves here because v1.0.0 must be usable remotely, and because ADR-0035 takes the station's trusted certificate from it. No public tunnel: a device that records audio stays off the public internet (ADR-0035).

### Prerequisites

| Milestone   | Feature                               |
| ----------- | ------------------------------------- |
| **v0.10.0** | Station API with authentication       |
| **v0.11.0** | Web-Interface                         |

---

## Phase 1: Decisions

### Tasks

- [ ] Accept or reject ADR-0035
- [ ] Decide how Tailscale runs on the station: on the host or in a container (an ADR, or an amendment to ADR-0035)

---

## Phase 2: HTTPS (ADR-0035)

**Goal:** Every name the station answers under gets a certificate; plain HTTP only redirects.

### Tasks

- [ ] The station's own certificate authority for LAN names (`silvasonic.local`, IP address)
- [ ] Installing the station's authority on a client is documented
- [ ] HTTP answers with a redirect only

---

## Phase 3: Tailscale

**Goal:** The station is reachable at `<station>.<tailnet>.ts.net` with a publicly trusted certificate.

### Tasks

- [ ] Tailscale on the station, joined to the owner's tailnet at installation
- [ ] Caddy obtains the certificate from the Tailscale daemon (`TS_PERMIT_CERT_UID` for the rootless user)
- [ ] Station names that do not identify owner or location (they appear in Certificate Transparency logs)
- [ ] The station keeps recording and stays usable on the LAN while Tailscale is down

---

## Out of Scope (Deferred)

| Item                                   | Target Version |
| -------------------------------------- | -------------- |
| Fleet-wide access to many stations     | post-v1.0.0    |
| Metered uplinks (LTE, satellite)       | v1.5.0         |
