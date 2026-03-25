# User Testing

Testing surface, required testing skills/tools, resource cost classification per surface.

---

## Validation Surface

This mission has NO web UI. The validation surface is entirely CLI/pytest-based:

- **Primary surface:** pytest test suite
  - Run: `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python -m pytest test/ -v --no-header -x --ignore=test/test_api.py`
  - All assertions are verified by running pytest and checking pass/fail
  - AWS tests require `--run-aws` flag

- **Secondary surface:** psql spot-checks
  - Validators may run ad-hoc SQL queries to verify counts
  - Local: `psql -U postgres -h localhost -p 5432 -d quantdb_test`
  - AWS: `psql "host=troy-quantdb-test.crxhhfokqjgu.us-east-1.rds.amazonaws.com port=5432 dbname=postgres user=postgres sslmode=require"`

## Required Tools

- pytest (installed in quantdb conda env)
- psql (system PostgreSQL client)
- No browser testing tools needed

## Validation Concurrency

Machine: 128GB RAM, 16 cores. No resource constraints.
Max concurrent validators: **5** (each validator runs pytest which connects to PostgreSQL; 5 concurrent DB connections is well within limits).

For the `gold-standard-snapshots` milestone, the effective concurrency is **1** despite the machine ceiling above. The snapshot tests share the same `quantdb_test` database and rely on the session-scoped `rebuild_database` fixture, which drops/restores the database; concurrent pytest validators against that same DB can interfere with each other.

For the `extraction-layer` milestone, the effective concurrency is also **1** for the current assertion set. The user-testing flow only needs one targeted pytest selection covering cache-backed entity extraction and JPX path extraction assertions, so extra parallel validators would add overhead without improving coverage.

For the `deep-upsert-ingest` milestone, the effective concurrency is **1** as well. The real validation flow mutates the shared `quantdb_test` singleton database through an extract -> delete -> re-ingest cycle for dataset `f006`, so concurrent validators would interfere with each other's baseline and post-ingest assertions.

## Test Markers

- Default: runs all non-AWS tests
- `@pytest.mark.aws`: tests requiring AWS RDS (skip by default)
- Custom conftest.py needed to register `--run-aws` flag and skip aws-marked tests when flag not present

## Known Issues

- `test/test_api.py` must always be ignored (CROSS JOIN LATERAL bug)
- 16 SQLAlchemy automap warnings are cosmetic and expected
- `test_ingest_f006.py::rebuild_database` fixture takes ~30s for pg_restore of 33MB dump
- `test/test_ingest_v2.py` currently emits `PytestUnknownMarkWarning` for `@pytest.mark.slow`; the warning is harmless for validation runs but expected until the mark is registered

## Flow Validator Guidance: cli-pytest

- Use `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python` for all Python and pytest commands.
- Stay on the real CLI/pytest surface: validate with pytest and, if needed, read-only `psql` spot checks.
- Ignore `test/test_api.py` on every pytest invocation.
- Treat `quantdb_test` on localhost as a shared singleton resource. Do not run milestone pytest flows concurrently against it.
- For `extraction-layer`, validate only the assertions still fulfilled by the completed milestone features: `VAL-EXT-001`, `VAL-EXT-002`, `VAL-EXT-005`, and `VAL-EXT-006`. `VAL-EXT-003` and `VAL-EXT-004` were deferred by the orchestrator to the ingest milestone because the cached cassava metadata does not contain the required CSV entries.
- For `deep-upsert-ingest`, start with `test/test_ingest_v2.py::TestComparisonProof` on the real database surface, then add read-only SQL/Python spot checks if needed to verify user-visible contract details that the test selection may not fully prove (for example exact value preservation or `obj_desc_*` metadata fidelity).
- Keep writes inside the validator's assigned report path under `.factory/validation/<milestone>/user-testing/flows/` and evidence path under the mission directory.
