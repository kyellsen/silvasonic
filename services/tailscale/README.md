# Container: Tailscale

> **Service Name:** `tailscale`
> **Container Name:** `silvasonic-tailscale`
> **Package Name:** `silvasonic-tailscale` (Docker Image Only)

## 1. The Problem / The Gap
*   **Remote Access:** Devices are deployed in forests/fields behind CGNAT mobile networks. No public IP is available for SSH/Web access.
*   **Security:** Exposing ports to the open internet is dangerous.

## 2. User Benefit
*   **Connect from Anywhere:** Securely access the Dashboard and SSH terminal from home, even if the device is on 4G.
*   **Zero Config:** Mesh logic handles NAT traversal automatically.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Network Packet Steam**.
    *   **Auth Key**: For initial registration.
*   **Processing**:
    *   **WireGuard Tunneling**: Encrypting traffic.
    *   **Subnet Routing**: (Optional) Exposing the device LAN.
*   **Outputs**:
    *   **Virtual Network Interface**: `tailscale0`.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Low**. Background daemon.
*   **State**: **Stateful**. Must store identity keys (`/var/lib/tailscale`).
*   **Privileges**: **Elevated**. Requires `CAP_NET_ADMIN` and access to `/dev/net/tun` to create VPN interfaces.
*   **Resources**: Low.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `TS_authkey`: Ephemeral key for setup.
    *   `TS_hostname`: Device Name.
*   **Volumes**:
    *   `silvasonic-tailscale-state` -> `/var/lib/tailscale`.
*   **Dependencies**:
    *   `/dev/net/tun` (Device Node).

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** manage application logic.
*   **Does NOT** bypass local firewall rules (still needs valid ports allowed on the interface).
*   **Does NOT** serve as a general purpose web server (Gateway job).
*   **Does NOT** analyze network traffic contents (just tunnels it).
*   **Does NOT** store recordings.

## 7. Technology Stack
*   **Base Image**: `tailscale/tailscale:stable`.
*   **Key Libraries**:
    *   WireGuard (Go Implementation).
*   **Build System**: Docker Hub Upstream.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Standard solution for IoT remote access.
*   **Alternatives**: OpenVPN/WireGuard manual setup (Requires a central server with public IP; Tailscale manages the control plane).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** None detected.
