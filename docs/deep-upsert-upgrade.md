# Deep Upsert: Generic Ingestion Layer for quantdb

## Why

The original `generic_ingest.py` on master failed at the `aspects` table due to automap relationship naming mismatches and missing FK propagation event listeners. It required hardcoded Pydantic models for each table and manual FK integer management -- callers had to know the dependency graph and insert parent rows in the right order before inserting children.

The goal was to make the 20-table relational schema feel like a single table: pass human-readable strings, get automatic FK resolution, no babysitting.

## How

Three-layer architecture in `quantdb/generic_ingest.py`:

### Layer 1: Schema Introspection (`SchemaGraph`)

Built once during `reflect_models()` by walking `Base.metadata`. Produces:

- FK dependency graph mapping every FK column to its target table, model, and natural key columns
- Topological sort (6 levels, from root tables like `units`/`aspects` down to leaf tables `values_quant`/`values_cat`)
- Table classification: lookup (pre-populated, read-only) vs create (data tables)
- Circular dependency detection (`objects <-> objects_internal`)
- Natural key identification from unique constraints

### Layer 2: FK Resolution Primitives

- **`get_or_create(session, Model, natural_key_cols, data)`** -- race-safe upsert. Handles IDENTITY PK exclusion, IS NULL semantics for nullable unique columns, server-default awareness.
- **`resolve_fk_value(session, schema, table, col, value, cache)`** -- type-based resolution: `str` -> natural key lookup, `dict` -> composite key with recursive resolution, `int`/`UUID` -> pass-through, `None` -> NULL.
- **`deep_upsert(session, Model, schema, data, cache)`** -- recursively resolves all FK columns in a data dict. Transaction-scoped cache prevents redundant queries. Auto-creates trigger-ordered prerequisites (`obj_desc_inst`, `obj_desc_quant`, `obj_desc_cat`).

### Layer 3: User API (`Ingest`)

```python
from quantdb.models import reflect_models
from quantdb.generic_ingest import Ingest

models = reflect_models(engine=engine)
ing = Ingest(models)

with ing.session() as s:
    ing.row(s, 'values_quant',
            value=42.0, value_blob=42.0,
            object='<uuid>',
            desc_inst='nerve',
            desc_quant='count',
            instance={'dataset': '<uuid>', 'id_formal': 'sub'})

    results = ing.batch(s, 'values_quant', rows)
    unit = ing.get(s, 'units', label='um')
```

- `row()` / `batch()` -- insert with automatic FK resolution. `batch()` shares an FK cache across rows.
- `get()` -- lookup by natural key. Returns `None` if not found.
- `session()` -- context manager: commits on success, rolls back on exception.
- Lookup table protection: raises `LookupTableError` on writes to pre-populated tables (units, aspects, descriptors, etc.).
- Human-readable error messages wrapping PostgreSQL constraint/trigger failures.

### Key Design Decisions

- **Flat dict API** -- no Pydantic models, no nested objects. FK resolution inferred from value types.
- **Transaction-scoped cache** -- keyed by `(table_name, frozenset(natural_key_items))`. 100 rows referencing the same unit = 1 SELECT.
- **`flush()` not `commit()` during recursion** -- auto-generated PKs become available without committing mid-transaction.
- **Trigger ordering** -- `values_quant`/`values_cat` require prerequisite rows in `obj_desc_inst` + `obj_desc_quant`/`obj_desc_cat` (PostgreSQL triggers). `deep_upsert` auto-creates these.
- **Schema introspection once at reflect time** -- no repeated metadata walks at insert time.

## Where

| File | What |
|------|------|
| `quantdb/generic_ingest.py` | Entire ingestion layer (SchemaGraph, primitives, Ingest class) |
| `quantdb/models.py` | Added `schema_graph` field to `ReflectedModels`; built during `reflect_models()` |
| `test/test_generic_ingest.py` | 39 unit tests for SchemaGraph |
| `test/test_deep_upsert.py` | 43 integration tests (deep upsert, Ingest API, E2E, batch, trigger ordering) |
| `test/conftest.py` | Shared pytest fixtures |
| `docs/fk-dependency-report.md` | FK dependency graph reference (20 tables, 6 topo levels) |
| `docs/generic_ingest_failure_analysis.md` | Post-mortem of the failed master branch approach |
| `docs/research-deep-upsert-patterns.md` | Research notes on upsert patterns evaluated |

### Public API

| Symbol | Type | Purpose |
|--------|------|---------|
| `SchemaGraph` | class | FK dependency graph, built via `SchemaGraph.from_reflected(models)` |
| `Ingest` | class | User-facing API: `row()`, `batch()`, `get()`, `session()` |
| `get_or_create` | function | Race-safe idempotent row creation by natural key |
| `resolve_fk_value` | function | Type-based FK resolution (str/dict/int/UUID/None) |
| `deep_upsert` | function | Recursive FK resolution with trigger ordering |
| `IngestError` | exception | Base ingestion failure |
| `LookupTableError` | exception | Write attempt to pre-populated lookup table |
| `TableInfo` | dataclass | Per-table metadata (pk, fk_map, natural_key, topo_level, is_lookup) |
| `FKInfo` | namedtuple | Per-FK-column metadata (target_table, target_col, natural_key_cols) |

## Testing

All tests run against a live `quantdb_test` database on localhost:5432. No cassava/AWS endpoints are called -- tests use reference data already in the database (pre-loaded from a production pg_dump).

```sh
# Run all tests (excluding pre-existing test_api.py failure)
pytest test/ -v --no-header -x --ignore=test/test_api.py
```

82 tests across 3 files. Tests use `session.rollback()` teardown so no data persists.

## Known Constraints

- **orthauth config**: `secrets.sxpr` resolves to AWS RDS. Always pass an explicit localhost engine to `reflect_models(engine=engine)`.
- **objects.id**: Requires a user-supplied UUID (Pennsieve-provided), not auto-generated.
- **No update/delete**: `get_or_create` is idempotent but won't update changed non-key columns. No delete support.
- **Batch scaling**: `batch()` does per-row `deep_upsert` with shared cache. For 10k+ rows, `executemany` or COPY would be faster.

## Future Work

- Wire `Ingest` into Flask API endpoints (POST/PUT in `api.py`)
- Add `Ingest.update()` and `Ingest.delete()` methods
- Fix orthauth config so explicit engine construction isn't needed
- Handle `objects_internal` circular dependency in auto-creation helpers
- Fix pre-existing `test_api.py` CROSS JOIN LATERAL bug
