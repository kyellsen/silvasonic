# Milestone v0.7.0 — Gateway (Reverse Proxy)

> **Target:** v0.7.0 — Gateway (Caddy reverse proxy, HTTPS termination, internal routing)
>
> **Status:** ⏳ Planned
>
> **References:** [ADR-0014: Dual Deployment Strategy](../../adr/0014-dual-deployment-strategy.md), [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md), [Port Allocation](../../arch/port_allocation.md)
>
> **User Stories:** [US-GW01](../../user_stories/gateway.md#us-gw01), [US-GW02](../../user_stories/gateway.md#us-gw02), [US-GW03](../../user_stories/gateway.md#us-gw03)

---

## Phase 1: Service Architecture

**Goal:** Create the `gateway` service adhering to the Service Blueprint.

### Tasks

- [ ] Scaffold `services/gateway/` and `Caddyfile`
- [ ] Configure Caddyfile for internal routing and API access
- [ ] Implement internal TLS for silvasonic.local via `tls internal`
- [ ] Setup Basic Auth in Caddy for MVP
- [ ] Integrate Gateway into compose.yml and .env

*(Further phases and tasks will be detailed as development begins)*

---

## Out of Scope (Deferred)

| Item                   | Target Version |
| ---------------------- | -------------- |
| None                  | n/a            |
