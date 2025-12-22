#!/bin/bash
set -e

echo "=== Step 1: Reset test database ==="
./bin/dbsetup 5432 quantdb_test

echo "=== Step 2: Run F006 ingestion (using ingestion/f006_ingest.py - NEW) ==="
source ~/miniforge3/etc/profile.d/conda.sh && conda activate quant
python ingestion/f006_ingest.py

echo "=== Step 3: Export to CSV ==="
python ingestion/db2csv.py -o ./export

echo "=== Pipeline complete ==="
ls -la ./export/
