# silvasonic-tailscale

> **Status:** Planned (v1.5.0) · **Tier:** 1 (Infrastructure) · **Instances:** Single

**TO-BE:** Tailscale provides secure, zero-config remote access and VPN mesh networking for the Silvasonic platform. It allows administrators to connect to the Web-Interface from anywhere without exposing ports to the public internet or configuring complex port forwarding on field routers.

---

## The Problem / The Gap

*   **Remote Management:** Field stations are often deployed behind CGNAT (Carrier-Grade NAT) on cellular networks, making incoming connections impossible without a dedicated VPN tunnel.
*   **Security:** Exposing the Web-Interface directly to the internet is a massive security risk. We need a secure, encrypted overlay network.
*   **SSL Certificates:** Using auto-HTTPS (like Caddy) on a local/private network usually results in browser certificate warnings, which degrades user trust.

## User Benefit

*   **Access Anywhere:** Manage your recording stations securely from your laptop or phone, no matter where they are deployed.
*   **Valid HTTPS:** Tailscale MagicDNS integrates with Caddy to provide valid, globally trusted TLS certificates for the private IP (e.g., `https://station-1.tailnet-name.ts.net`), removing annoying browser warnings.

---

## Core Responsibilities

*   **VPN Tunnel:** Establishes an outbound encrypted connection to the Tailscale coordination server, creating a mesh network.
*   **Subnet Router (Optional):** Can expose the entire local subnet to the Tailscale network.
*   **Caddy Integration:** Tailscale runs within the same network namespace as the Gateway, allowing Caddy to request TLS certificates via the Tailscale socket.

---

## Operational Constraints & Rules

| Aspect           | Value / Rule                                                                  |
| ---------------- | ----------------------------------------------------------------------------- |
| **Immutable**    | Yes — config via Auth Key at startup.                                         |
| **DB Access**    | **No**.                                                                       |
| **Concurrency**  | High network throughput.                                                      |
| **State**        | Maintains Tailscale identity state in a local volume.                         |
| **Privileges**   | Requires `NET_ADMIN` and `NET_RAW` capabilities to manage network interfaces. |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure (Life Support).           |

---

## Architecture Context

*   **Deployment:** Tailscale runs as a container next to the Gateway. The Gateway routes its traffic *through* the Tailscale network namespace to listen on the Tailscale IP.

## Out of Scope

*   **Does NOT** route internet traffic (it is an overlay VPN, not an exit node by default).
*   **Does NOT** serve the web interface itself.
