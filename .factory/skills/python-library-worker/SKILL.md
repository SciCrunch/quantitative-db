---
name: python-library-worker
description: Implements Python library modules with TDD against a PostgreSQL database
---

# Python Library Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features that implement Python library code (classes, functions, modules) with test coverage. Specifically:
- Building schema introspection utilities
- Implementing get-or-create and deep upsert primitives
- Creating user-facing API classes
- Writing unit tests (no DB) and integration tests (against live PostgreSQL)

## Required Skills

None.

## Work Procedure

### Step 1: Read Feature Context

1. Read `mission.md` for overall mission goals
2. Read `AGENTS.md` for boundaries and conventions
3. Read `.factory/library/architecture.md` for module structure and design decisions
4. Read `.factory/library/environment.md` for Python/DB setup details
5. Read `.factory/services.yaml` for test commands
6. Read the assigned feature's description, preconditions, expectedBehavior, and verificationSteps

### Step 2: Understand Existing Code

1. Read `quantdb/models.py` to understand the reflected ORM models
2. Read `sql/tables.sql` to understand the database schema (FK constraints, triggers, unique constraints)
3. Read any existing code in `quantdb/generic_ingest.py` (may have been created by prior features)
4. Read existing test files to understand test patterns (especially `test/test_ingest_f006.py` for integration test fixtures)
5. Read the research reports in `docs/` for FK dependency analysis, failure analysis, and design patterns

### Step 3: Write Tests First (RED)

1. Create or update the test file specified in the feature
2. Write failing tests that assert the expected behavior from the feature description
3. Run tests with `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3 -m pytest <test_file> -v --no-header -x` to confirm they fail
4. For unit tests: use mocks/fixtures, no database required
5. For integration tests: use the `reflected` and `session` fixture pattern from `test_models.py` or the `rebuild_database` pattern from `test_ingest_f006.py`

### Step 4: Implement (GREEN)

1. Implement the code in the module file specified in the feature
2. Follow the existing code style in the repo:
   - Type hints on all function signatures
   - Google-style docstrings with Args/Returns sections
   - `from __future__ import annotations` at top of new files
3. Run tests again to confirm they pass
4. Fix any failures

### Step 5: Verify

1. Run the full test suite: `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3 -m pytest test/ -v --no-header -x --ignore=test/test_api.py`
2. Ensure no regressions in existing tests
3. Check for import errors on the symbols YOUR feature created (not future features)
4. Verify no external URLs in YOUR test files (not all of test/ — test/test_ingest_f006.py intentionally contains cached cassava references): `rg 'amazonaws|cassava\.ucsd' test/test_deep_upsert.py test/test_generic_ingest.py`
5. Run pre-commit formatters on changed files: `cd "/Users/tmsincomb/Dropbox (Personal)/repos/quantitative-db" && pre-commit run --files <your_files>` and commit any fixes

### Step 6: Commit

1. `git add` only the files you created/modified
2. Write a concise commit message describing what was implemented
3. Do NOT commit docs/ research files or .factory/ files

## CRITICAL CONSTRAINTS

- **Python binary**: ALWAYS use `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3` (not system python3)
- **No AWS**: NEVER reference amazonaws, cassava.ucsd.edu, or any external endpoint in test code
- **No schema changes**: NEVER modify `sql/tables.sql` or any SQL DDL files
- **No API changes**: NEVER modify `quantdb/api.py` or `quantdb/ingest.py`
- **Flush not commit**: Use `session.flush()` inside recursive functions, `session.commit()` only at outermost level
- **Test isolation**: Use `session.rollback()` in test teardown to avoid polluting the database

## Example Handoff

```json
{
  "salientSummary": "Implemented SchemaGraph.from_reflected() that introspects Base.metadata to build FK dependency graph with topological sort across all 20 tables. Wrote 12 unit tests in test_generic_ingest.py (all passing). Full test suite: 86/87 pass (1 pre-existing failure in test_api.py).",
  "whatWasImplemented": "SchemaGraph class with from_reflected() classmethod, TableInfo and FKInfo dataclasses, FK map construction from Table.foreign_keys, natural key detection from UniqueConstraint introspection, topological sort via Kahn's algorithm, circular dependency detection for objects<->objects_internal, table classification (lookup vs create). Added schema_graph field to ReflectedModels namedtuple.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3 -m pytest test/test_generic_ingest.py -v --no-header -x",
        "exitCode": 0,
        "observation": "12 tests passed including TestSchemaGraph (7 tests) and TestFKInfo (5 tests)"
      },
      {
        "command": "/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3 -m pytest test/ -v --no-header -x",
        "exitCode": 0,
        "observation": "86/87 tests passed. 1 pre-existing failure in test_api.py (inst-parent SQL bug, unrelated)"
      },
      {
        "command": "rg 'amazonaws|cassava\\.ucsd' test/",
        "exitCode": 1,
        "observation": "No external URLs found in test files (exit code 1 = no matches)"
      }
    ],
    "interactiveChecks": []
  },
  "tests": {
    "added": [
      {
        "file": "test/test_generic_ingest.py",
        "cases": [
          {"name": "test_schema_graph_builds_from_reflected", "verifies": "SchemaGraph construction succeeds"},
          {"name": "test_topo_order_roots_before_leaves", "verifies": "Root tables appear before leaf tables"},
          {"name": "test_fk_map_descriptors_quant", "verifies": "FK map has unit, aspect, domain entries"},
          {"name": "test_natural_key_units", "verifies": "units natural key is ['label']"},
          {"name": "test_circular_deps_detected", "verifies": "objects<->objects_internal detected"},
          {"name": "test_association_tables_present", "verifies": "All 5 association tables in graph"},
          {"name": "test_table_classification", "verifies": "Lookup vs create classification correct"}
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Feature depends on a module or function that doesn't exist yet and wasn't created by a prior feature
- The database schema doesn't match what's documented (tables missing, columns different)
- A pre-existing test regression blocks verification (beyond the known test_api.py failure)
- Requirements are ambiguous about how to handle a specific edge case (e.g., circular dependency resolution strategy)
