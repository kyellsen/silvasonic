# ADR-0035: HTTPS and Certificates

> **Status:** Proposed • **Date:** 2026-11-10

## 1. Context & Problem

The Gateway serves plain HTTP today. That is not enough for what is planned:

*   the session cookie of [ADR-0034](0034-authentication-and-authorization.md) is `Secure` and is not sent over HTTP;
*   a password typed on a shared Wi-Fi would be readable;
*   an installable app on a phone needs a service worker, and browsers register one only over HTTPS **with a certificate they trust**; passkeys have the same condition.

A station sits in a private network. It has no public address, so a certificate authority cannot reach it to verify a name, and the names it has there (`silvasonic.local`, an IP address) are names no public authority certifies. This is the general problem of HTTPS for local devices; there is no solution without a trade-off.

## 2. Decision

**We chose:** HTTPS on every hostname, with the certificate chosen by the name the station is reached under. A name that can carry a publicly trusted certificate gets one automatically; every other name gets a certificate from the station's own authority. Plain HTTP only redirects.

**Reasoning:**

*   **The Gateway (Caddy) stays the single listener** and terminates TLS. Services behind it speak HTTP on the internal network, as US-GW02 states.
*   **Trusted: the Tailscale name.** For `<station>.<tailnet>.ts.net` Caddy fetches a Let's Encrypt certificate from the Tailscale daemon on the station, with no configuration of its own. The name resolves at home and on the road, without port forwarding. This is the supported way to use the dashboard as an installed app and from outside the local network.
*   **Fallback: local names.** For `silvasonic.local` and IP addresses Caddy issues a certificate from an authority it creates on the station at first start. The connection is encrypted; the browser warns once, because it cannot know that authority. The dashboard works; the installable app and passkeys do not.
*   **The API tells the dashboard which origins are trusted** (`GET /info`, `trusted_origins`), and the dashboard points a user on a fallback name to the trusted one.
*   **`Strict-Transport-Security` is sent on trusted names only.**
*   **Nobody is asked to install a root certificate**, and no image contains key material: every station creates its own.
*   **Later, with a fleet:** a station gets a name under the product's domain and its certificate through the DNS-01 challenge, which the fleet server answers on the station's behalf while the private key never leaves the station. That gives a trusted certificate without software on the phone. It needs the fleet server and has its own trade-offs, so it is decided there.

## 3. Options Considered

*   **Plain HTTP in the local network:** Rejected. No `Secure` cookie, readable credentials, no installable app.
*   **Self-signed certificates only:** Rejected as the main path. Every browser on every phone warns, the installable app never works, and users learn to click warnings away. It remains the fallback, for the lack of anything better on a local name.
*   **A vendor authority whose root users install:** Rejected. It would let the vendor impersonate any site to those users, and installing a root on an iPhone is more than a hobby user should have to do.
*   **A public name that resolves to the private address, now:** Deferred to the fleet. It needs a DNS zone and a broker run by the vendor, and routers that block such answers — the DNS rebind protection of a FRITZ!Box does by default — need an exception per household.
*   **`tailscale serve` in front of the Gateway:** Not chosen, kept in reserve. It yields the same certificate with a second place that terminates TLS. It is the way out if handing the Tailscale socket to the rootless Gateway container proves fragile.
*   **A public tunnel (Tailscale Funnel, Cloudflare Tunnel):** Rejected. It puts a device that records audio on the public internet.

## 4. Consequences

*   **Positive:**
    *   Encryption everywhere without anything to configure; a trusted certificate without anything to buy or renew.
    *   The dashboard can be installed on a phone and used from anywhere, once the phone is in the tailnet.
*   **Negative:**
    *   The trusted path needs a Tailscale account, HTTPS certificates enabled for the tailnet and the Tailscale app on each phone or laptop.
    *   Certificate names are published in Certificate Transparency logs; a station's Tailscale name should not identify its owner or location.
    *   A user who stays on the local name sees a warning and cannot install the app.
    *   The Gateway container needs access to the Tailscale daemon's socket, and the daemon must permit the rootless user to request certificates (`TS_PERMIT_CERT_UID`).
    *   Issuing and renewing need internet access; a station offline for longer than a certificate lives falls back to the local authority until it is back.
*   **On acceptance these documents change:** `docs/services/gateway.md`, `docs/services/tailscale.md` (Tailscale moves ahead of v1.5.0 as the certificate source), `services/gateway/Caddyfile`.
