# Deprecated Ingestion Files

These files have been superseded by `ingestion/f006_ingest.py` which uses:
- `automap_base` for dynamic model reflection (no hardcoded ORM)
- `back_populate_with_dependencies` for FK-aware insertion
- YAML-driven configuration

## Deprecated Files

| File | Original Purpose |
|------|-----------------|
| `f006.py` | Generic study template approach |
| `f006_csv.py` | CSV processing with hardcoded models |
| `f006_csv_with_export.py` | CSV processing with debug export |
| `f006_ingestion_aligned.py` | Aligned with quantdb/ingest.py |
| `f006_updated.py` | Value-generating function pattern |
| `f006_with_export.py` | Basic ingestion with export |
| `generic_study_template.py` | Abstract base class approach |

## Migration

Replace imports from these files with:

```python
from ingestion.f006_ingest import F006Ingestion, run_f006_ingestion
```

Or use the lower-level components:

```python
from quantdb.automap_client import get_automap_session
from quantdb.generic_ingest import back_populate_with_dependencies
```
