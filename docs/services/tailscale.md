# Tailscale Service

> **Status:** Planned (v1.5.0) · **Tier:** 1 · **Instances:** Single · **Ports:** None (VPN overlay)

Secure, zero-config remote access via WireGuard-based VPN mesh networking. Enables SSH, Web-Interface, and fleet management access to field-deployed devices behind CGNAT or mobile networks.

---

## 1. The Problem / The Gap

*   **Remote Access:** Devices are deployed in forests and fields behind CGNAT mobile networks. No public IP is available for SSH or Web-Interface access.
*   **Security:** Exposing ports to the open internet is dangerous and impractical for resource-constrained IoT devices.

## 2. User Benefit

*   **Connect from Anywhere:** Securely access the Web-Interface dashboard and SSH terminal from home, even when the device is on 4G/LTE.
*   **Zero Config:** Tailscale's mesh logic handles NAT traversal, key rotation, and peer discovery automatically — no manual WireGuard configuration or central VPN server required.

## 3. Core Responsibilities

### Inputs

*   **Network Packets:** Incoming/outgoing traffic from the Tailscale coordination server and peer nodes.
*   **Auth Key:** Pre-authenticated key for headless device registration (no browser login on RPi).

### Processing

*   **WireGuard Tunneling:** Encrypts all traffic between the device and the Tailscale mesh network.
*   **Subnet Routing:** (Optional) Exposes the device's local LAN to the Tailscale network.

### Outputs

*   **Virtual Network Interface:** `tailscale0` — the device becomes reachable via a stable Tailscale IP (e.g., `100.x.y.z`) and MagicDNS hostname.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                                                             |
| ---------------- | -------------------------------------------------------------------------------------------------------- |
| **Immutable**    | No — long-running daemon, maintains persistent VPN state                                                 |
| **DB Access**    | No                                                                                                       |
| **Concurrency**  | Low — single tunnel, event-driven                                                                        |
| **State**        | Stateful — stores node keys, peer state, and authentication tokens                                       |
| **Privileges**   | Requires `NET_ADMIN` capability and `/dev/net/tun` device access (NOT `privileged: true` — see ADR-0007) |
| **Resources**    | Low — minimal CPU and memory footprint                                                                   |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                                                      |

> [!IMPORTANT]
> Tailscale must **NOT** use `privileged: true` (ADR-0007). Instead, grant the specific capabilities it needs: `cap_add: [NET_ADMIN, NET_RAW]` and device access `/dev/net/tun`. This follows the principle of least privilege.

## 5. Configuration & Environment

| Variable / Mount | Description                                   | Default / Example                                             |
| ---------------- | --------------------------------------------- | ------------------------------------------------------------- |
| `TS_AUTHKEY`     | Pre-authenticated key for headless enrollment | (secret, from Tailscale admin console)                        |
| `TS_HOSTNAME`    | Device hostname on the Tailscale network      | `silvasonic-fieldstation-01`                                  |
| `TS_STATE_DIR`   | Persistent state directory                    | `/var/lib/tailscale`                                          |
| State mount      | Tailscale node keys and state (persisted)     | `${SILVASONIC_WORKSPACE_PATH}/tailscale:/var/lib/tailscale:z` |
| `/dev/net/tun`   | TUN device access for WireGuard tunnel        | —                                                             |

## 6. Technology Stack

*   **Base Image:** `tailscale/tailscale:stable`
*   **VPN Protocol:** WireGuard (Go implementation, built into Tailscale)
*   **Build:** Upstream Docker Hub image — no custom Containerfile needed

> [!NOTE]
> Tailscale is **not a Python service** — it has no `pyproject.toml`, no `SilvaService`, and does not publish Redis heartbeats. It is a pure infrastructure container using the upstream vendor image. The Service Blueprint does not apply.

## 7. Open Questions & Future Ideas

*   Tailscale ACLs for restricting which users can access which devices
*   Tailscale SSH (direct SSH via Tailscale identity without local SSH keys)
*   Subnet routing for accessing other devices on the station's local network
*   Tailscale Funnel for temporary public HTTPS access (e.g., for demos)
*   Alternatives considered and rejected: Manual WireGuard (requires a central server with public IP), OpenVPN (heavier, less modern)

## 8. Out of Scope

*   **Does NOT** manage application logic (Controller's job).
*   **Does NOT** serve as a web server (Gateway's job).
*   **Does NOT** analyze or inspect network traffic contents — it only tunnels.
*   **Does NOT** replace the Gateway — Tailscale provides network-level access, Gateway provides HTTP-level routing.
*   **Does NOT** store recordings or application data (Database / filesystem's job).

## 9. References

*   [ADR-0007](../adr/0007-rootless-os-compliance.md) — Rootless OS Compliance (Tailscale must NOT use `privileged: true`)
*   [Port Allocation](../arch/port_allocation.md) — No dedicated ports (VPN overlay)
*   [Hardware: Network Requirements](../hardware.md) — WireGuard/Tailscale network requirements
*   [Glossary](../glossary.md) — Tier 1 definition
*   [VISION.md](../../VISION.md) — roadmap entry (v1.5.0)
