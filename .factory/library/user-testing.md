# User Testing

**What belongs here:** Testing surface, required tools, resource cost, validation approach.

---

## Validation Surface

**Surface type:** Python pytest (CLI)
**Tool:** `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3 -m pytest`
**No browser testing needed** — this is a pure Python library.

### Test Files
- `test/test_generic_ingest.py` — Unit tests for SchemaGraph, FK resolution (no DB required)
- `test/test_deep_upsert.py` — Integration tests against live `quantdb_test` database
- `test/test_models.py` — Existing tests for reflected models (should still pass)

### How to Validate
1. Run unit tests: `commands.test-unit` from services.yaml
2. Run integration tests: `commands.test-integration` from services.yaml
3. Run all tests: `commands.test` from services.yaml
4. Verify no external network calls: `rg 'amazonaws|cassava\.ucsd' test/`

### Database State
- `quantdb_test` on localhost:5432 is pre-loaded with production data (restored from dump)
- Reference data (units, aspects, descriptors_inst, etc.) already populated via inserts.sql
- Tests should use `session.rollback()` after each test to avoid pollution
- Integration tests that need a clean DB should use the `rebuild_database` fixture pattern

## Validation Concurrency

**Max concurrent validators:** 5
**Rationale:** pytest with 128GB RAM and 16 cores. Each pytest process uses ~200MB. Even 5 concurrent runs = 1GB, well within budget. PostgreSQL can handle concurrent read sessions easily.

## CRITICAL CONSTRAINT

All validation must use **localhost:5432 only**. Zero tolerance for AWS/external network connections.

## Flow Validator Guidance: pytest-cli

- Treat the testing surface as **read-mostly CLI/Python validation** against the local repo and `quantdb_test`.
- Use `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python3` for all Python commands.
- Use explicit localhost engine construction for any direct Python checks:
  `create_engine(dbUri('quantdb-test-user', 'localhost', 5432, 'quantdb_test'))`.
- Do **not** use `reflect_models()` with implicit config or `reflect_models(test=True)` during user testing, because mission guidance says orthauth can resolve to AWS.
- Stay inside the repo and assigned report/evidence paths only.
- Do not mutate shared database state unless the assigned assertion requires it; for schema-engine validation, prefer read-only reflection/tests.
- Write one JSON flow report per assigned assertion group and include exact commands, exit codes, and observed results.
