#!/bin/bash
# Smoke test - verify all services are up
# Usage: ./scripts/smoke_test.sh

set -e

echo "==> Testing Postgres..."
docker exec thinkcanvas-postgres pg_isready -U thinkcanvas

echo "==> Testing Redis..."
docker exec thinkcanvas-redis redis-cli ping

echo "==> Testing backend health (if running)..."
if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    curl -s http://localhost:8000/api/v1/health
    echo ""
else
    echo "Backend not running (start with: uvicorn app.main:app --port 8000)"
fi

echo "==> Testing frontend (if running)..."
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "Frontend OK"
else
    echo "Frontend not running (start with: cd frontend && npm run dev)"
fi

echo "✅ Smoke test done"
