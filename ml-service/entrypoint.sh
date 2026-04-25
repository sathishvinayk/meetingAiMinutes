#!/bin/bash
set -e

echo ""
echo "════════════════════════════════════════════════════════"
echo "🚀 MeetingPulse - ML Service Starting"
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

# Verify Whisper is installed
echo "🔍 Checking Whisper installation..."
python -c "import whisper; print('✅ Whisper installed successfully')" 2>/dev/null || {
    echo "⚠️ Whisper not found, installing..."
    pip install openai-whisper --quiet
}

# Check if phi3:mini model exists
MODEL_EXISTS=$(curl -s http://ollama:11434/api/tags | grep -c "phi3:mini" 2>/dev/null || echo "0")

if [ "$MODEL_EXISTS" = "0" ]; then
    echo "📥 Downloading phi3:mini model (3.8B parameters) - This happens ONLY ONCE..."
    curl -s -X POST http://ollama:11434/api/pull -d '{"name": "phi3:mini"}' > /dev/null
    echo "✅ Model download complete!"
else
    echo "✅ phi3:mini model already exists (using cached version)"
fi

# Check if protobuf files exist, generate if missing
if [ ! -f "meeting_pb2.py" ]; then
    echo "⚠️ Protobuf files missing, generating..."
    python -m grpc_tools.protoc -I./proto --python_out=. --grpc_python_out=. ./proto/meeting.proto
    echo "✅ Protobuf files generated"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "🎤 Starting Whisper + Phi-3 ML Service"
echo "════════════════════════════════════════════════════════"
echo ""

# Start Python service
exec python -u main.py
