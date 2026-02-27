#!/bin/bash
set -e

echo "Running Alembic migrations..."
cd "$(dirname "$0")/.."
alembic upgrade head
echo "Migrations complete."
