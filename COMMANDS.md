# More Commands:
git pull
podman-compose down --volumes
podman-compose -f podman-compose.yml up -d --build
podman-compose -f podman-compose.yml up -d --build

podman logs -f silvasonic-status-board

# Cleanup: 

The Bomb: podman-compose down --volumes --images all
The Nuke: podman system prune -a --volumes --force

Alle Container stoppen und entfernen: podman rm -af

Alle ungenutzten Netzwerke entfernen: podman network prune -f

Volumes entfernen (da du --volumes genutzt hast): podman volume prune -f