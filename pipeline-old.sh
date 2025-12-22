#!/bin/bash
set -e

echo "=== Step 1: Reset test database ==="
./bin/dbsetup 5432 quantdb_test

echo "=== Step 2: Run F006 ingestion (using ingestion/f006_ingest.py) ==="
source ~/miniforge3/etc/profile.d/conda.sh && conda activate quant
python ingestion/f006_ingest.py

echo "=== Step 3: Export to CSV ==="
python ingestion/db2csv.py -o ./export_old

echo "=== Step 4: Compare with previous export ==="
if [ -d "./export" ]; then
    echo "Comparing export_old vs export..."
    diff -rq ./export_old ./export && echo "SUCCESS: Exports are identical" || echo "DIFFERENCE: Exports differ"
else
    echo "No ./export directory to compare against. Run pipeline.sh first."
fi

echo "=== Pipeline complete ==="
ls -la ./export_old/
