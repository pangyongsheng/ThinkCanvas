#!/bin/bash
# 一键启动本地开发环境
# Usage: ./scripts/dev.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==> 1. Starting infrastructure (Postgres + Redis)..."
cd docker
docker compose up -d
cd ..

echo "==> Waiting for services to be ready..."
sleep 5

echo "==> 2. Setting up Python venv..."
if [ ! -d "backend/.venv" ]; then
    python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate

echo "==> 3. Installing Python dependencies..."
pip install --upgrade pip
pip install -e "backend[dev]"

echo "==> 4. Running database migrations..."
cd backend
alembic upgrade head
cd ..

echo "==> 5. Installing frontend dependencies..."
if [ ! -d "frontend/node_modules" ]; then
    cd frontend && npm install && cd ..
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the dev servers, run in 3 separate terminals:"
echo "  Terminal 1: cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000"
echo "  Terminal 2: cd backend && source .venv/bin/activate && rq worker -u redis://localhost:6379/0"
echo "  Terminal 3: cd frontend && npm run dev"
echo ""
echo "Then open http://localhost:3000"
