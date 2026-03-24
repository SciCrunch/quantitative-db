# Environment

**What belongs here:** Required env vars, external dependencies, setup notes.
**What does NOT belong here:** Service ports/commands (use `.factory/services.yaml`).

---

## Python Environment

- Conda env: `/Users/tmsincomb/miniforge3/envs/quantdb/`
- Python: 3.12+ (in conda env)
- System python3 (3.14) does NOT have SQLAlchemy — always use conda env
- Package installed in editable mode: `pip install -e ".[dev]"`
- Key dependencies: SQLAlchemy 2.0.40, psycopg2-binary 2.9.10, Flask-SQLAlchemy 3.1.1, pytest 8.3.5

## Database

- PostgreSQL 16.13 (Homebrew) on localhost:5432
- Trust auth (no passwords for localhost connections)
- Test database: `quantdb_test` (20 tables in `quantdb` schema)
- User: `quantdb-test-user` (SELECT, INSERT privileges)
- Search path: `quantdb, public` (set via event listener in models.py)

## Auth Config

- orthauth config at `~/.config/quantdb/config.yaml`
- `test-db-*` keys point to localhost quantdb_test
- `db-*` keys commented out (production requires explicit env vars)
- Because orthauth resolution can still be overridden to AWS, tests that reflect models should construct an explicit localhost engine and call `reflect_models(engine=engine)` rather than relying on the no-arg default.

## CRITICAL CONSTRAINT

- **NO AWS/external network calls.** All tests must use localhost:5432 only.
- Never connect to `*.amazonaws.com` or `cassava.ucsd.edu` from test code.
- As of 2026-03-24, the full suite command `pytest test/ -v --no-header -x` fails immediately in `test/test_api.py` because the Flask API path still opens a SQLAlchemy connection to `sparc-nlp.cpmk2alqjf9s.us-west-2.rds.amazonaws.com` instead of localhost, which raises `psycopg2.OperationalError: fe_sendauth: no password supplied`.
