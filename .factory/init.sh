#!/usr/bin/env bash
set -euo pipefail

PYTHON="/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3"
REPO_DIR="/Users/tmsincomb/Dropbox (Personal)/repos/quantitative-db"

# Verify conda env exists and has SQLAlchemy
"$PYTHON" -c "import sqlalchemy; import pytest; import quantdb" 2>/dev/null || {
    echo "ERROR: conda quantdb env missing dependencies. Run: conda activate quantdb && pip install -e '.[dev]'"
    exit 1
}

# Verify PostgreSQL is running and quantdb_test is accessible
psql -U quantdb-test-user -h localhost -p 5432 -d quantdb_test -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='quantdb'" -t -A 2>/dev/null | grep -q "20" || {
    echo "ERROR: quantdb_test database not accessible or missing tables."
    echo "Ensure PostgreSQL is running and quantdb_test has 20 tables in the quantdb schema."
    exit 1
}

echo "Environment ready: Python=$($PYTHON --version), PostgreSQL=localhost:5432, DB=quantdb_test"
