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
