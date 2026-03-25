#!/bin/bash
set -e

echo "NewsForge starting..."

# Run database migrations
echo "Running database migrations..."
cd /app/backend
PYTHONPATH=/app/backend python -m alembic upgrade head

# Create data directories
mkdir -p /app/data/articles

echo "Starting services via supervisord..."
exec supervisord -c /app/docker/supervisord.conf
