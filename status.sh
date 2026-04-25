#!/bin/bash

echo ""
echo "════════════════════════════════════════════════════════"
echo "📊 MeetingPulse Status"
echo "════════════════════════════════════════════════════════"
echo ""

docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "🌐 Open: http://localhost:3000"
echo ""

# Check if services are healthy
if docker compose ps | grep -q "Up"; then
    echo "✅ All services are running"
else
    echo "⚠️ Some services are not running. Check with: docker compose logs"
fi
