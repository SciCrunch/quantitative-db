---
name: db-pipeline-worker
description: Implements Python database pipeline modules with TDD against PostgreSQL
---

# Database Pipeline Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Features involving:
- SQL schema additions (lookup data inserts, enum modifications)
- Python extraction modules (parsing CSV, GraphML, JSON from APIs)
- Python ingestion pipelines (FK-safe insertion into PostgreSQL)
- Integration tests against a real PostgreSQL database
- Round-trip proof tests (extract → delete → re-ingest → compare)

## Required Skills

- `sqlalchemy20` — Invoke for SQLAlchemy 2.0 patterns when writing database queries or ORM code.

## Work Procedure

### 1. Understand the Feature

Read the feature description, preconditions, expectedBehavior, and verificationSteps carefully. Read these key reference files:
- `docs/ingest-v2-reference.md` — Full ingestion reference
- `MicroCTDataStandard/MicroCTDataStandard.md` — MicroCT data standard
- `quantdb/ingest_v2.py` — f006 ingestion pattern to follow
- `quantdb/extract_v2.py` — f006 extraction pattern to follow
- `quantdb/generic_ingest.py` — Ingest API (batch, row, deep_upsert)
- `.factory/library/architecture.md` — System architecture

### 2. Write Tests First (TDD)

**Before writing any implementation code**, write failing tests:
- For SQL schema features: test that new lookup data exists in the database
- For extraction features: test function outputs (dict structure, key correctness, value ranges)
- For ingestion features: test table counts, hierarchy integrity, spot-check values
- For round-trip features: test extract → delete → re-ingest count equality

Run tests to confirm they fail: `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest {test_file} -v`

### 3. Implement

Follow patterns from existing code:
- **SQL inserts**: Use `ON CONFLICT DO NOTHING` for idempotency. Use `DO $$ ... END $$` blocks for ALTER TYPE with IF NOT EXISTS guard.
- **Extraction**: Return flat dicts with string FK labels. Follow `extract_entities_v2()` pattern for cassava fetch. Use `urllib.request` or `requests` for HTTP.
- **Ingestion**: Follow `ingest_f006_v2()` pattern. Use `Ingest.batch()` for small tables, pre-resolved bulk SQL for large. Pre-create obj_desc_* prerequisites. Use `DISABLE TRIGGER USER`.
- **Deletion**: Follow `delete_f006_data()` pattern. Child-first FK-safe ordering.

**Critical patterns to follow:**
```python
# Flat dict format for values_quant
{'value': 42.0, 'value_blob': 42.0, 'object': uuid_str,
 'desc_inst': 'nerve-cross-section', 'desc_quant': 'nerve cross section area um2',
 'instance': {'dataset': uuid_str, 'id_formal': 'sub-SR001'}}

# Pixel conversion
PIXEL_TO_UM = 11.4
PIXEL_TO_UM2 = 129.96  # 11.4 * 11.4

# FK lookup building
di_map = {label: id for id, label in session.execute(
    select(DI.id, DI.label)).all()}

# Bulk insert with triggers disabled
session.execute(text('ALTER TABLE quantdb.values_quant DISABLE TRIGGER USER'))
session.execute(insert(VQ.__table__), resolved_rows)
session.execute(text('ALTER TABLE quantdb.values_quant ENABLE TRIGGER USER'))
```

### 4. Run Tests

Run the test suite to verify implementation:
```bash
/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest {test_file} -v
```

Fix any failures iteratively until all tests pass.

### 5. Verify Manually

For schema features:
```bash
/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -c "
import psycopg2
conn = psycopg2.connect(dbname='quantdb_test', host='localhost', port=5432)
cur = conn.cursor()
cur.execute('SELECT label FROM quantdb.units ORDER BY label')
print([r[0] for r in cur.fetchall()])
conn.close()
"
```

For ingestion features: verify counts directly via SQL queries.

### 6. Run Lint

```bash
/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m flake8 quantdb/extract_microct.py quantdb/ingest_microct.py --max-line-length=120
```

## Example Handoff

```json
{
  "salientSummary": "Implemented MicroCT extraction module with cassava fetch, NerveMorphology CSV parsing (pixel→um conversion), GraphML node+edge parsing, and SummaryMorphology CSV parsing. All 14 extraction tests pass including hierarchy completeness and FK label validation.",
  "whatWasImplemented": "Created quantdb/extract_microct.py with functions: fetch_cassava_metadata(), extract_microct_entities(), parse_nerve_morphology_csv(), parse_fascicle_graphml(), parse_summary_morphology(), parse_data_wrapper(). Each function returns flat dicts with string FK labels matching the Ingest API format. Created test/test_extract_microct.py with 14 test cases covering all extraction functions.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/test_extract_microct.py -v",
        "exitCode": 0,
        "observation": "14 passed in 12.3s. All extraction tests green."
      },
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m flake8 quantdb/extract_microct.py --max-line-length=120",
        "exitCode": 0,
        "observation": "No lint errors."
      }
    ],
    "interactiveChecks": [
      {
        "action": "Verified cassava fetch returns valid JSON for MicroCT dataset",
        "observed": "curation-export.json has 3 subjects, 15 samples. path-metadata.json has 200+ file entries."
      },
      {
        "action": "Spot-checked pixel→um conversion on known NerveMorphology row",
        "observed": "area=100 pixels → 12996.0 um2 (100 * 129.96). Correct."
      }
    ]
  },
  "tests": {
    "added": [
      {
        "file": "test/test_extract_microct.py",
        "cases": [
          {"name": "test_cassava_fetch_curation_export", "verifies": "Valid JSON structure from cassava"},
          {"name": "test_entity_extraction_subjects", "verifies": "Non-empty subjects with correct keys"},
          {"name": "test_nerve_morphology_csv_parsing", "verifies": "Correct flat dict format with um conversion"},
          {"name": "test_graphml_node_parsing", "verifies": "Fascicle node measurements extracted correctly"},
          {"name": "test_graphml_edge_parsing", "verifies": "Edge properties as categorical dicts"},
          {"name": "test_hierarchy_completeness", "verifies": "Every child has parent except root subjects"}
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Cassava API returns unexpected data structure or errors
- Required lookup table labels don't exist (schema feature not applied)
- Database connection fails or quantdb_test doesn't exist
- Circular FK workaround for objects_internal fails in unexpected way
- GraphML files have unexpected structure not matching MicroCT data standard
- Test database rebuild_database fixture fails
