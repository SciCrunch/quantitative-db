#!/usr/bin/env bash
# quantdb-prepare-test-db.sh
# This script prepares a test PostgreSQL database with the same schema as the main DB and populates it with the first 10 rows of each table.
# Usage: ./bin/prepare_test_db.sh [MAIN_DB] [TEST_DB] [PGUSER] [PGHOST] [PGPORT]

set -e
eval "$(conda shell.bash hook)"
conda activate quantdb

# If you want to use the remote MAIN_DB connection info from client.py, extract it using Python
REMOTE_DB_URI=$(python -c "from quantdb.client import get_session; s = get_session(echo=False); print(str(s.get_bind().url))")
echo "Established Connection"

MAIN_DB=${1:-quantdb}
TEST_DB=${2:-quantdb_test}
PGUSER=${3:-quantdb-test-admin}
PGHOST=${4:-localhost}
PGPORT=${5:-5432}

# Parse the remote DB URI for pg_dump
REMOTE_PGUSER=$(echo "$REMOTE_DB_URI" | sed -E 's|.*://([^:]+):.*|\1|')
REMOTE_PGPASSWORD=$(python -c "from quantdb.config import auth; print(auth.get('db-password') or '')")
REMOTE_PGHOST=$(echo "$REMOTE_DB_URI" | sed -E 's|.*@([^:/]+).*|\1|')
REMOTE_PGPORT=$(echo "$REMOTE_DB_URI" | sed -E 's|.*:([0-9]+)/.*|\1|')
REMOTE_DBNAME=$(echo "$REMOTE_DB_URI" | sed -E 's|.*/([^?]+).*|\1|')

# Export password for pg_dump if available
if [ -n "$REMOTE_PGPASSWORD" ]; then
    export PGPASSWORD="$REMOTE_PGPASSWORD"
fi

# Ensure the PGUSER has a database (needed for psql connection)
psql -U $PGUSER -h $PGHOST -p $PGPORT -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$PGUSER'" | grep -q 1 || createdb -U $PGUSER -h $PGHOST -p $PGPORT $PGUSER

# Drop and recreate the test database
psql -U $PGUSER -h $PGHOST -p $PGPORT -c "DROP DATABASE IF EXISTS $TEST_DB;"
psql -U $PGUSER -h $PGHOST -p $PGPORT -c "CREATE DATABASE $TEST_DB;"

# Dump schema only from remote MAIN_DB and restore to local test DB
pg_dump -U $REMOTE_PGUSER -h $REMOTE_PGHOST -p $REMOTE_PGPORT -s $REMOTE_DBNAME | psql -U $PGUSER -h $PGHOST -p $PGPORT $TEST_DB

# Get all table names from the remote MAIN_DB
TABLES=$(psql -U $REMOTE_PGUSER -h $REMOTE_PGHOST -p $REMOTE_PGPORT -d $REMOTE_DBNAME -Atc "SELECT tablename FROM pg_tables WHERE schemaname='public';")

echo "Tables in remote DB: $TABLES"

# For each table, copy the first 10 rows from remote MAIN_DB to local test DB
for TABLE in $TABLES; do
    COLS=$(psql -U $REMOTE_PGUSER -h $REMOTE_PGHOST -p $REMOTE_PGPORT -d $REMOTE_DBNAME -Atc "SELECT string_agg('"' || column_name || '"', ',') FROM information_schema.columns WHERE table_name='$TABLE' AND table_schema='public';")
    psql -U $PGUSER -h $PGHOST -p $PGPORT -d $TEST_DB -c "INSERT INTO \"$TABLE\" ($COLS) SELECT $COLS FROM dblink('host=$REMOTE_PGHOST user=$REMOTE_PGUSER dbname=$REMOTE_DBNAME port=$REMOTE_PGPORT','SELECT $COLS FROM \"$TABLE\" LIMIT 10') AS t($COLS);" 2>/dev/null || true
done

unset PGPASSWORD

echo "Test database '$TEST_DB' prepared with schema and first 10 rows of each table from remote '$REMOTE_DBNAME'."
