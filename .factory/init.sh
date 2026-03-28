#!/bin/bash
set -e

CONDA_ENV="/Users/tmsincomb/miniforge3/envs/quantdb"
PYTHON="$CONDA_ENV/bin/python"
PIP="$CONDA_ENV/bin/pip"

# Install networkx for GraphML parsing (idempotent)
$PIP install networkx 2>/dev/null || true

# Install project in editable mode (idempotent)
$PIP install -e . 2>/dev/null || true

# Verify PostgreSQL is running
/opt/homebrew/opt/postgresql@16/bin/pg_isready -h localhost -p 5432 || {
    echo "ERROR: PostgreSQL not running on localhost:5432"
    exit 1
}

# Verify quantdb_test database exists
$PYTHON -c "import psycopg2; psycopg2.connect(dbname='quantdb_test', host='localhost', port=5432).close()" 2>/dev/null || {
    echo "WARNING: quantdb_test database not accessible. Tests may need rebuild_database fixture."
}

echo "Environment ready."
