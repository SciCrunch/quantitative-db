# QuantDB - Quantitative Database

A database schema and ingestion system for storing arbitrary quantitative measurements, particularly focused on biological and scientific datasets (e.g., nerve morphology from microCT and immunohistochemistry).

## Quick Start

### Prerequisites

- PostgreSQL (local or remote)
- Python 3.9+ with conda
- Database credentials configured in `~/.pgpass`

### Environment Setup

```bash
# Activate conda environment
source /path/to/miniforge3/etc/profile.d/conda.sh && conda activate quant

# Install dependencies
pip install -e .
pip install -e ".[dev]"  # For development
```

### Database Setup

```bash
# Setup test database
./bin/prepare_test_db.sh

# Or manually setup database
./bin/dbsetup [PORT] [DATABASE]
```

## F006 Dataset Ingestion

The F006 dataset contains human vagus nerve anatomical reconstruction using microCT, immunohistochemistry, and ultrasound.

**Dataset UUID:** `2a3d01c0-39d3-464a-8746-54c9d67ebe0f`

### Running Ingestion

#### Test Database (Recommended for Development)

```bash
# Basic test run
python ingestion/f006_ingest.py --test

# Dry run (no commit)
python ingestion/f006_ingest.py --test --dry-run

# Limit CSV files processed (for quick testing)
python ingestion/f006_ingest.py --test --csv-limit 10
```

#### Production Database

```bash
# Production run (use with caution!)
python ingestion/f006_ingest.py --prod

# Production dry run first
python ingestion/f006_ingest.py --prod --dry-run
```

### Programmatic Usage

```python
from ingestion.f006_ingest import F006Ingestion, run_f006_ingestion

# Simple usage
result = run_f006_ingestion(test=True, commit=True)
print(f"Created {result['instances']} instances")

# Advanced usage with custom session
from quantdb.automap_client import get_automap_session

session, models = get_automap_session(test=True)
ingestion = F006Ingestion(models)
result = ingestion.run(session, commit=True, csv_limit=10)
session.close()
```

### Verifying Ingestion

```python
from quantdb.automap_client import get_automap_session

session, models = get_automap_session(test=True)

# Check counts
Objects = models['objects']
ValuesInst = models['values_inst']

print(f"Objects: {session.query(Objects).count()}")
print(f"Instances: {session.query(ValuesInst).count()}")

session.close()
```

## Architecture

### Dynamic Model Reflection

The ingestion system uses `sqlalchemy.ext.automap` for dynamic model reflection, eliminating the need for hardcoded ORM models:

```python
from quantdb.automap_client import get_automap_session, get_insert_order

session, models = get_automap_session(test=True)
# models is a dict: {'objects': ObjectsClass, 'values_inst': ValuesInstClass, ...}
```

### Key Components

| Module | Purpose |
|--------|---------|
| `quantdb/automap_client.py` | Dynamic model reflection and session factory |
| `quantdb/generic_ingest.py` | Core ingestion functions (`get_or_create_dynamic`, `back_populate_with_dependencies`) |
| `ingestion/f006_ingest.py` | F006-specific ingestion logic |
| `ingestion/f006_interlex_mappings.yaml` | YAML configuration for descriptors |

### Data Flow

```
YAML Config ─────┐
                 ├──> F006Ingestion ──> back_populate_with_dependencies ──> PostgreSQL
Cached Metadata ─┘
```

## Configuration

### Database Credentials

Configure PostgreSQL credentials in `~/.pgpass`:

```
localhost:5432:quantdb_test:quantdb-test-admin:your-password
localhost:5432:quantdb:quantdb-admin:your-password
```

### YAML Mappings

Dataset-specific configurations are in `ingestion/f006_interlex_mappings.yaml`:

```yaml
aspects:
  - iri: http://uri.interlex.org/...
    label: diameter

descriptors:
  instance_types:
    - iri: http://uri.interlex.org/ilx_0738300
      label: fiber-cross-section
```

## Testing

```bash
# Run all tests
pytest

# Run specific ingestion tests
pytest test/test_generic_ingest.py -v

# Skip database tests
pytest -m "not database"
```

## Deprecated Files

Legacy ingestion files have been moved to `ingestion/deprecated/`. See `ingestion/deprecated/README.md` for migration guidance.

## Project Structure

```
quantitative-db-fork/
├── quantdb/
│   ├── automap_client.py    # Dynamic model reflection
│   ├── generic_ingest.py    # Core ingestion functions
│   ├── client.py            # Legacy session factory
│   └── ingest.py            # Original hardcoded ingestion
├── ingestion/
│   ├── f006_ingest.py       # New minimal F006 ingestion
│   ├── f006_interlex_mappings.yaml
│   ├── data/                # Cached metadata
│   └── deprecated/          # Legacy files
├── sql/
│   ├── tables.sql           # Schema definition
│   └── inserts.sql          # Base data
└── test/
```

## License

See [LICENSE](LICENSE) file.
