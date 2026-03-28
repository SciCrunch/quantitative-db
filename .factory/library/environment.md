# Environment

**What belongs here:** Required env vars, external dependencies, setup notes.
**What does NOT belong here:** Service ports/commands (use `.factory/services.yaml`).

---

## Python Environment

- **Use conda env `quantdb`**: `/Users/tmsincomb/miniforge3/envs/quantdb/`, Python 3.12
- **Do NOT use `.venv/`** — different SQLAlchemy version, missing sparcur
- Key packages: SQLAlchemy 2.0.40, pytest 8.3.5, psycopg2, networkx (for GraphML)
- Activate: `source /Users/tmsincomb/miniforge3/bin/activate quantdb`

## Database

- PostgreSQL 16 on localhost:5432
- Test database: `quantdb_test`
- Production dump: `resources/quantdb_production_template.dump`
- pg_restore: `/opt/homebrew/opt/postgresql@16/bin/pg_restore`

## External APIs

- Cassava: `https://cassava.ucsd.edu/sparc/datasets/{uuid}/LATEST/`
- MicroCT dataset UUID: `fb1cbd05-4320-4d8b-ac3a-44f1fe810718`

## Code Conventions

- Formatter: blue (via pre-commit)
- Linter: flake8
- Test runner: pytest
- Use `DISABLE TRIGGER USER` (not ALL) for AWS RDS compatibility
