# User Testing

## Validation Surface

This is a data pipeline project — no browser UI or CLI surface. All validation is through the pytest test suite running against a local PostgreSQL database.

**Primary surface:** pytest tests in `test/test_ingest_microct.py` and `test/test_extract_microct.py`
**Tool:** pytest (via conda env quantdb)
**Database:** quantdb_test on localhost:5432

## Validation Concurrency

**Surface: pytest**
- Tests run sequentially (single pytest process)
- Database rebuild is session-scoped (expensive, runs once)
- Max concurrent validators: 1 (single database, session-scoped fixture)
- Rationale: Tests share a single quantdb_test database; parallel test runs would cause data conflicts

## Setup Notes

- Use conda env: `/Users/tmsincomb/miniforge3/envs/quantdb`
- Prepare environment with: `"/bin/bash" ".factory/init.sh"`
- Ensure PostgreSQL healthcheck passes at `localhost:5432`
- Primary schema/extraction commands:
  - `python -m pytest test/test_schema_microct.py -v`
  - `python -m pytest test/test_extract_microct.py -v`

## Flow Validator Guidance: pytest

- Isolation boundary: shared `quantdb_test` database on `localhost:5432`; do not run concurrent pytest validators.
- Work only from repo root `/Users/tmsincomb/Dropbox (Personal)/repos/quantitative-db`.
- Use the shared conda env binary directly: `/Users/tmsincomb/miniforge3/envs/quantdb/bin/python`.
- It is safe to apply `sql/inserts_microct.sql` because the schema test already exercises idempotency.
- Do not mutate production/business logic during validation; only run setup, pytest commands, and write flow reports/evidence under `.factory/validation/` or the mission `evidence/` directory.
