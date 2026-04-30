#!/bin/bash
# One-command setup for any platform

echo "🚀 meetingAiHackathon - Cross-Platform Setup"
echo "======================================"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

# Start Docker if not running (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! docker info &> /dev/null; then
        echo "Starting Docker Desktop..."
        open -a Docker
        sleep 10
    fi
fi

# Run the start script
./start.sh
