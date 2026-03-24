# Architecture

**What belongs here:** Architectural decisions, patterns, module structure.

---

## Module Structure

```
quantdb/
├── models.py          # automap_base reflection → ReflectedModels namedtuple (20 ORM classes)
├── generic_ingest.py  # NEW: SchemaGraph + deep_upsert + Ingest class
├── api.py             # Flask API server (DO NOT MODIFY)
├── ingest.py          # Raw SQL ingest pipelines (DO NOT MODIFY)
├── config.py          # orthauth config
├── utils.py           # dbUri helper, logging
└── exceptions.py      # Custom exceptions
```

## Key Design Decisions

### Schema Introspection at Reflect Time
`SchemaGraph` is built once during `reflect_models()` by introspecting `Base.metadata`. It maps FK columns → target tables → natural keys. This avoids repeated introspection at insert time.

### FK Resolution by Value Type
- `str` value on FK column → lookup target table by single-column natural key (e.g., `label`)
- `dict` value on FK column → lookup by composite natural key columns
- `int`/`UUID` value → pass through (pre-resolved)
- `None` → NULL (for nullable FKs)

### flush() Not commit() During Recursion
All recursive `deep_upsert` calls use `session.flush()` to make auto-generated PKs available within the transaction. `commit()` only happens at the outermost call site (the Ingest.session() context manager or explicit caller).

### Transaction-Scoped Cache
A `dict` cache keyed by `(table_name, frozenset(natural_key_values))` prevents redundant SELECTs within a single transaction. Shared across `batch()` calls.

## Schema Facts (from FK Dependency Report)

- 20 tables total: 5 root, 2 leaf, rest intermediate
- Max FK chain depth: 3 (values_quant → obj_desc_quant → descriptors_quant → units)
- 1 circular dependency: objects ↔ objects_internal
- 5 association tables with composite FK-only PKs
- All integer serial PKs resolvable by natural key lookup
- Only objects.id requires user-supplied UUID (Pennsieve ID)

## Existing Patterns to Follow

- `models.py` uses `_snake_to_camel()` for table→class name mapping
- `models.py` uses `_disambiguated_scalar_name` / `_disambiguated_collection_name` for relationship naming
- `models.py` suppresses automap overlapping-relationship warnings (harmless for read-only ORM access)
- Test fixtures use `rebuild_database` pattern (see `test_ingest_f006.py`)
- Tests use `session.rollback()` after each test to avoid pollution
