# Environment

Environment variables, external dependencies, and setup notes.

**What belongs here:** Required env vars, external API keys/services, dependency quirks, platform-specific notes.
**What does NOT belong here:** Service ports/commands (use `.factory/services.yaml`).

---

## Python Environment

- Conda env: `quantdb` at `/Users/tmsincomb/miniforge3/envs/quantdb/`
- Python: 3.12
- Key packages: SQLAlchemy 2.0.40, pytest 8.3.5, psycopg2, sparcur 0.0.1.dev5, idlib, orthauth
- DO NOT use `.venv/` (different SQLAlchemy version, missing sparcur)

## sparcur Quirks

- `sparcur.objects` CANNOT be imported (module missing in this version)
- Safe imports: `sparcur.utils.PennsieveId`, `sparcur.utils.fromJson`, `sparcur.utils.register_type`, `sparcur.paths.Path`
- pennsieve SDK pinned to v6 (pennsieve<7)

## Database Credentials

- Local: trust auth (no password), user=quantdb-test-user or postgres
- AWS RDS: credentials in ~/.pgpass, user=postgres, SSL required
- orthauth config at ~/.config/quantdb/config.yaml: test-db-* = localhost, db-* = AWS test instance

## Cassava Data

- Public metadata API: https://cassava.ucsd.edu/sparc/datasets/{uuid}/LATEST/
- No auth needed for cassava
- Cached at ~/.quantdb/cassava.ucsd.edu.cache/
- Pennsieve API needed for actual file downloads (credentials in ~/.pennsieve/config.ini)
