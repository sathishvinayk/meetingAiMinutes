#!/bin/bash
set -e

echo ""
echo "════════════════════════════════════════════════════════"
echo "🚀 meetingAiHackathon - ML Service Starting"
echo "════════════════════════════════════════════════════════"
echo ""

# Wait for Ollama
echo "⏳ Waiting for Ollama to be ready..."
RETRY=0
MAX_RETRY=30
until curl -s http://ollama:11434/api/tags > /dev/null 2>&1; do
    RETRY=$((RETRY+1))
    if [ $RETRY -ge $MAX_RETRY ]; then
        echo "❌ Ollama failed to start"
        exit 1
    fi
    echo "   Waiting... ($RETRY/$MAX_RETRY)"
    sleep 2
done
echo "✅ Ollama is ready"
echo ""

# Generate protobuf files if needed
if [ ! -f "meeting_pb2.py" ]; then
    echo "📁 Generating protobuf files..."
    python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. ./proto/meeting.proto 2>/dev/null
    echo "✅ Protobuf files generated"
else
    echo "✅ Protobuf files found"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "🎤 Starting ML Service (Whisper + Phi-3)"
echo "════════════════════════════════════════════════════════"
echo ""

# Start Python service
exec python -u main.py