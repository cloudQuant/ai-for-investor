#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Starting ai-for-investor services..."

docker compose up -d

echo "All services started!"
echo "Frontend: http://localhost:3000"
echo "Backend API: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
