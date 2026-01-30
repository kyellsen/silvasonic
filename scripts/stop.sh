#!/bin/bash
set -e

echo "🛑 Stopping Silvasonic Stack..."

# Fährt Container runter und entfernt das Netzwerk (aber behält Volumes)
podman-compose down

echo "✅ Stack stopped."