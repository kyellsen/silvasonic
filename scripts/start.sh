#!/bin/bash
set -e

echo "🚀 Starting Silvasonic Stack (Rootless)..."

# Config Check
if [ ! -f .env ]; then
    echo "⚠️ .env not found. Copying from config.example.env..."
    cp config.example.env .env
fi

# Start Podman (Rootless, Detached)
podman-compose up --build -d

echo "✅ Stack started in background."
echo "📜 View logs with: make logs"