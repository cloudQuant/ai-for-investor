#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Restarting ai-for-investor services..."

docker compose restart

echo "All services restarted!"
