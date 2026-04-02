# User Stories — Gateway Service

> **Service:** Gateway · **Tier:** 1 (Infrastructure)

---

<a id="us-gw01"></a>
## US-GW01: Everything accessible via one address 🌐

> **As a user**
> **I want to** reach all functions of my station — dashboard, settings, live audio — via a single address in the browser,
> **so that** I don't have to remember different ports or URLs.

### Acceptance Criteria

- [ ] All web services (web interface, live stream) are accessible via a common address (e.g., `https://silvasonic.local`).
- [ ] The user doesn't need to know port numbers — routing to internal services happens automatically.
- [ ] Static content (CSS, images, fonts) is delivered compressed so the page loads quickly even on slow connections.
- [ ] If the gateway fails, recording and all other services continue undisturbed.

### References

- [Gateway Service Docs](../services/gateway.md)
- [Port Allocation](../arch/port_allocation.md)
- [Web-Interface Service Docs §Architecture](../services/web_interface.md)
- [Icecast Service Docs](../services/icecast.md)

---

<a id="us-gw02"></a>
## US-GW02: Connection is automatically encrypted 🔒

> **As a user**
> **I want** the connection to my station to be automatically encrypted,
> **so that** my credentials and data aren't transmitted in plaintext — without me having to manually set up certificates.

### Acceptance Criteria

- [ ] HTTPS is enabled by default — the user doesn't have to configure anything.
- [ ] HTTP requests are automatically redirected to HTTPS.
- [ ] On the local network, encryption works with a self-signed certificate; when connected via Tailscale, with a valid public certificate.
- [ ] Internal communication between the gateway and backend services remains unencrypted (no overhead in the internal network).

### Non-Functional Requirements

- Certificate management must run fully automatically — no manual renewal needed.

### References

- [Gateway Service Docs §TLS Termination](../services/gateway.md)
- [ADR-0014: Dual Deployment Strategy](../adr/0014-dual-deployment-strategy.md)

---

<a id="us-gw03"></a>
## US-GW03: Station is protected against unauthorized access 🛡️

> **As a user**
> **I want** my station to be protected by a password,
> **so that** not everyone on the network can access my recordings and settings.

### Acceptance Criteria

- [ ] No access to the web interface without login.
- [ ] Access protection applies uniformly to all services behind the gateway.
- [ ] When connected via Tailscale, authentication can optionally be handled via VPN identity.
- [ ] A default password is set during initial installation; the user is prompted to change it.

### References

- [Gateway Service Docs §Authentication](../services/gateway.md)
- [Web-Interface Service Docs §Access](../services/web_interface.md)

---

> [!NOTE]
> **Recording Protection:** This service must not impair the ongoing recording. Resource limits and prioritization are managed centrally by the Controller (→ [US-C04](./controller.md), [US-R02](./recorder.md)).
