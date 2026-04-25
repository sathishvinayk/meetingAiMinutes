#!/bin/bash
# Smart start script that works on any platform

set -e

echo "🚀 MeetingPulse - Cross-Platform Launcher"
echo "========================================="

# Detect platform
source ./detect-platform.sh

# Check Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Clean up old containers
echo "🧹 Cleaning up old containers..."
docker compose down -v 2>/dev/null || true

# Build for detected platform
echo "🔨 Building containers for $DOCKER_DEFAULT_PLATFORM..."
DOCKER_DEFAULT_PLATFORM=$DOCKER_DEFAULT_PLATFORM docker compose build --no-cache

# Start services
echo "🚀 Starting services..."
DOCKER_DEFAULT_PLATFORM=$DOCKER_DEFAULT_PLATFORM docker compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check status
echo ""
echo "📊 Service Status:"
docker compose ps

echo ""
echo "✅ MeetingPulse is running!"
echo "🌐 Frontend: http://localhost:3000"
echo "🔌 Backend API: http://localhost:8080"
echo "💚 Health check: http://localhost:8080/health"
echo ""
echo "📋 View logs: docker compose logs -f"
echo "🛑 Stop services: docker compose down"

# Open browser on macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:3000
fi
