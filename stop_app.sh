#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Stopping ai-for-investor services..."

docker compose down

echo "All services stopped!"
