#!/bin/bash
# Entrypoint script: run Alembic migrations then start the app.
set -e

echo "Running database migrations..."
cd /app
python -m alembic upgrade head

echo "Starting application..."
exec "$@"
