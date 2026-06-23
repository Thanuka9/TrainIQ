#!/usr/bin/env sh
# TrainIQ production web startup (Linux / macOS)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export FLASK_ENV="${FLASK_ENV:-production}"
export RUN_SCHEDULER="${RUN_SCHEDULER:-false}"
export EVENT_BUS_CONSUMER="${EVENT_BUS_CONSUMER:-false}"

echo "Running production preflight..."
python scripts/production_preflight.py

echo "Applying migrations..."
export FLASK_APP=app.py
flask db upgrade

echo "Starting gunicorn..."
exec gunicorn -c gunicorn.conf.py app:app
