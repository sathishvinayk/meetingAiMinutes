#!/bin/bash
# Platform detection script

echo "🔍 Detecting system architecture..."

# Detect OS
OS=$(uname -s)
echo "OS: $OS"

# Detect architecture
ARCH=$(uname -m)
echo "Architecture: $ARCH"

# Detect Docker platform
case "$ARCH" in
    x86_64|amd64)
        DOCKER_PLATFORM="linux/amd64"
        echo "✅ Detected: Intel/AMD 64-bit"
        ;;
    aarch64|arm64)
        DOCKER_PLATFORM="linux/arm64"
        echo "✅ Detected: ARM64 (Apple Silicon / Raspberry Pi)"
        ;;
    armv7l)
        DOCKER_PLATFORM="linux/arm/v7"
        echo "✅ Detected: ARM 32-bit"
        ;;
    *)
        DOCKER_PLATFORM="linux/amd64"
        echo "⚠️ Unknown architecture, defaulting to amd64"
        ;;
esac

# Check if running on Apple Silicon
if [[ "$OSTYPE" == "darwin"* ]] && [[ "$ARCH" == "arm64" ]]; then
    echo "🍎 Apple Silicon detected (M1/M2/M3)"
    export DOCKER_DEFAULT_PLATFORM="linux/arm64"
fi

# Export for docker-compose
export DOCKER_DEFAULT_PLATFORM=$DOCKER_PLATFORM
echo "DOCKER_DEFAULT_PLATFORM=$DOCKER_DEFAULT_PLATFORM"

# Save to .env file
echo "PLATFORM=$DOCKER_PLATFORM" > .env
echo "ARCH=$ARCH" >> .env

echo ""
echo "📝 Platform configuration saved to .env"
