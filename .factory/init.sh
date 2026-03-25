#!/usr/bin/env bash
set -e

# Verify conda quantdb env is available
PYTHON="/Users/tmsincomb/miniforge3/envs/quantdb/bin/python"
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: quantdb conda env not found at $PYTHON"
    exit 1
fi

# Verify key packages
$PYTHON -c "import sqlalchemy, pytest, psycopg2, sparcur; print('All packages OK')"

# Verify PostgreSQL is running
pg_isready -h localhost -p 5432 > /dev/null 2>&1 || {
    echo "ERROR: PostgreSQL not running on localhost:5432"
    exit 1
}

# Verify quantdb_test database exists
psql -U postgres -h localhost -p 5432 -c "SELECT 1" -d quantdb_test > /dev/null 2>&1 || {
    echo "ERROR: quantdb_test database not found"
    exit 1
}

# Verify production dump exists
DUMP="$(cd "$(dirname "$0")/.." && pwd)/resources/quantdb_production_template.dump"
if [ ! -f "$DUMP" ]; then
    echo "WARNING: Production dump not found at $DUMP"
fi

# Verify cassava cache exists
CACHE="$HOME/.quantdb/cassava.ucsd.edu.cache/2a3d01c0-39d3-464a-8746-54c9d67ebe0f"
if [ ! -d "$CACHE" ]; then
    echo "WARNING: Cassava cache not found at $CACHE"
fi

echo "Environment OK"
