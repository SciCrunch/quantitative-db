---
name: db-pipeline-worker
description: Implements Python database pipeline modules with TDD against PostgreSQL
---

# Database Pipeline Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features that involve:
- Writing Python modules that interact with PostgreSQL (quantdb schema)
- Creating pytest test files for database operations
- Writing SQL scripts for schema setup/teardown
- Building data extraction or ingestion pipelines
- Creating snapshot/fixture utilities

## Required Skills

None. All work is Python + PostgreSQL + pytest with no browser or TUI testing needed.

## Work Procedure

### Step 1: Understand the Feature

Read the feature description, preconditions, expectedBehavior, and verificationSteps carefully. Read AGENTS.md for boundaries and conventions. Read relevant `.factory/library/` files for architecture and environment context.

### Step 2: Examine Existing Code

Before writing anything, read the existing codebase files relevant to your feature:
- `quantdb/generic_ingest.py` - the Ingest API (SchemaGraph, deep_upsert, get_or_create)
- `quantdb/models.py` - reflected ORM models (ReflectedModels, reflect_models)
- `quantdb/ingest.py` - legacy ingest code (extract_* functions, ingest() function)
- `test/test_ingest_f006.py` - existing f006 tests with rebuild_database fixture
- `test/test_deep_upsert.py` - existing deep upsert tests with session fixture pattern

Understand the patterns used and follow them consistently.

### Step 3: Write Tests First (RED)

Write failing tests before implementation. Place test files in `test/` directory.

Key patterns to follow:
- Use `session.rollback()` teardown (see test_deep_upsert.py fixture pattern)
- Use explicit engine construction with search_path event listener (see AGENTS.md)
- Use the conda env python: `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python`
- Reuse `rebuild_database` fixture from test_ingest_f006.py where DB restore is needed
- Mark AWS tests with `@pytest.mark.aws`

Run tests to confirm they fail:
```bash
/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/<your_test_file>.py -v --no-header -x
```

### Step 4: Implement (GREEN)

Write the implementation to make tests pass. Place source modules in `quantdb/` directory.

Key patterns:
- Use `Ingest.batch()` / `Ingest.row()` for inserts (not raw SQL)
- Use `reflect_models(engine=engine)` with explicit engine (not orthauth defaults)
- String labels for FK columns in dicts passed to Ingest API
- Follow FK-safe deletion order when deleting data (see .factory/library/architecture.md)
- For fixtures: use `json.dumps(data, sort_keys=True, default=str)` for deterministic output

### Step 5: Run All Tests

Run the full test suite (excluding test_api.py) to ensure no regressions:
```bash
/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/ -v --no-header -x --ignore=test/test_api.py
```

All tests must pass (43 existing deep_upsert + your new tests).

### Step 6: Verify Manually

For database features, run ad-hoc verification:
```bash
# Check row counts directly
psql -U postgres -h localhost -p 5432 -d quantdb_test -c "SELECT count(*) FROM quantdb.values_inst WHERE dataset = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f';"
```

For fixture features, verify files exist and have expected content:
```bash
ls -la test/fixtures/f006/
```

### Step 7: Commit

Commit with a clear message describing what was implemented and tested.

## Example Handoff

```json
{
  "salientSummary": "Implemented snapshot extraction script and comparison utilities for f006 dataset. Created 11 fixture files in test/fixtures/f006/ with exact count verification. Tests confirm 609,390 values_inst rows with correct breakdown, 121 dataset_object links, and all small-table fixtures match production exactly. Comparison utility detects added/removed/modified rows across all tables.",
  "whatWasImplemented": "quantdb/snapshot.py with extract_f006_snapshot() and compare_snapshots() functions. test/test_snapshot.py with 15 tests covering fixture creation, count accuracy, breakdown verification, determinism, and comparison utility edge cases. Fixture files committed to test/fixtures/f006/.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/test_snapshot.py -v --no-header -x",
        "exitCode": 0,
        "observation": "15 passed, 0 failed"
      },
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/ -v --no-header -x --ignore=test/test_api.py",
        "exitCode": 0,
        "observation": "58 passed (43 existing + 15 new), 16 warnings"
      },
      {
        "command": "ls test/fixtures/f006/",
        "exitCode": 0,
        "observation": "11 fixture files present: values_inst_summary.json, dataset_object.json, etc."
      },
      {
        "command": "psql -U postgres -h localhost -p 5432 -d quantdb_test -c \"SELECT count(*) FROM quantdb.values_inst WHERE dataset = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f';\"",
        "exitCode": 0,
        "observation": "609390 rows confirmed"
      }
    ],
    "interactiveChecks": []
  },
  "tests": {
    "added": [
      {
        "file": "test/test_snapshot.py",
        "cases": [
          {"name": "test_fixture_files_created", "verifies": "VAL-SNAP-001"},
          {"name": "test_values_inst_count_and_breakdown", "verifies": "VAL-SNAP-002"},
          {"name": "test_dataset_object_matches", "verifies": "VAL-SNAP-003"}
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Database schema has unexpected differences from what AGENTS.md describes
- Production dump restore fails or produces different counts than expected
- sparcur import fails for allowed modules (PennsieveId, fromJson, etc.)
- AWS RDS connection fails (for Milestone 4 features)
- Feature depends on a module that doesn't exist yet (ordering issue)
- Cassava cache files are missing or corrupted
