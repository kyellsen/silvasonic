# Host Setup (Rootless)

Run these commands on the host (as user `pi`) to prepare the environment:

```bash
# 1. Add User to Hardware Groups (USB, GPIO, Audio)
sudo usermod -aG plugdev,dialout,audio,gpio $USER

# 2. Allow Unprivileged Port Binding (for Caddy/HTTP)
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/99-silvasonic.conf
sudo sysctl --system

# 3. Enable Service Persistence (Run without login)
sudo loginctl enable-linger $USER

# 4. Enable User Service
systemctl --user enable --now silvasonic.service
```
