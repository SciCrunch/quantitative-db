# F006 Dataset Ingestion Implementation

This directory contains a complete implementation of table-to-table data ingestion for dataset F006 using the `quantdb/generic_ingest.py` approach and SQLAlchemy ORM models.

## Overview

**Dataset ID**: `2a3d01c0-39d3-464a-8746-54c9d67ebe0f`

This implementation demonstrates how to:
1. Use the generic ingestion functions from `quantdb/generic_ingest.py`
2. Leverage SQLAlchemy ORM models instead of raw SQL
3. Implement a complete table-to-table ingestion workflow
4. Structure data extraction and transformation logic

## Files

### Core Implementation
- **`f006.py`** - Main ingestion script using ORM approach
- **`data/f006_path_metadata.json`** - Mock path metadata for testing

### Key Features

#### 1. ORM-Based Approach
Unlike the raw SQL approach in `ingest.py`, this implementation uses:
- SQLAlchemy ORM models from `quantdb/models.py`
- `get_or_create()` and `back_populate_tables()` helper functions
- Automatic relationship handling

#### 2. Table-to-Table Ingestion
The script demonstrates complete ingestion into multiple tables:

**Root Tables (No dependencies):**
- **Addresses**: Data source locations (constant and tabular-header types)
- **Aspects**: Measurement aspects (volume, length, diameter)
- **Units**: Measurement units (mm3, mm, um)
- **ControlledTerms**: Controlled vocabulary (microct)
- **DescriptorsInst**: Instance descriptors (human, nerve-volume, nerve-cross-section)
- **Objects**: Dataset and package objects

**Intermediate Tables (Depend on root tables):**
- **DescriptorsCat**: Categorical descriptors (hasDataAboutItModality)
- **DescriptorsQuant**: Quantitative descriptors (nerve-volume-mm3, nerve-cross-section-diameter-um)
- **ValuesInst**: Subject and sample instances

#### 3. Structured Data Pipeline
```python
# 1. Load metadata from local file (replaces API calls)
metadata = load_path_metadata()

# 2. Create necessary descriptors
components = create_basic_descriptors(session)

# 3. Ingest objects table
dataset_obj, packages = ingest_objects_table(session, metadata, components)

# 4. Ingest instances table
instances = ingest_instances_table(session, metadata, components, dataset_obj)
```

## Data Structure

### Input Data
The mock path metadata includes 4 files:
```
sub-f006/sam-l-seg-c1/microct/image001.jpx
sub-f006/sam-r-seg-c1/microct/image002.jpx
sub-f006/sam-l-seg-c2/microct/image003.jpx
sub-f006/sam-r-seg-c2/microct/image004.jpx
```

### Generated Database Records

#### Objects Table
- 1 dataset object (`2a3d01c0-39d3-464a-8746-54c9d67ebe0f`)
- 4 package objects (one per file)

#### Values Instance Table
- 1 subject instance (`sub-f006`)
- 4 sample instances (`sam-l-seg-c1`, `sam-r-seg-c1`, `sam-l-seg-c2`, `sam-r-seg-c2`)

#### Supporting Tables Created
- **Root Tables**: All 6 root tables (Addresses, Aspects, Units, ControlledTerms, DescriptorsInst, Objects)
- **Intermediate Tables**: DescriptorsCat, DescriptorsQuant, ValuesInst
- **Quantitative Descriptors**:
  - nerve-volume-mm3 (uses volume aspect and mm3 unit)
  - nerve-cross-section-diameter-um (uses diameter aspect and um unit)

## Testing

All test files are now centralized in the `test/` directory for better organization.

### Structural Validation (✅ PASSED)
```bash
# From project root
python3 test/test_f006_structure.py
```

This test validates:
- ✅ Data loading from JSON files
- ✅ Path structure parsing
- ✅ Dataset UUID consistency
- ✅ Ingestion logic with mocked components

### Integration Tests with Database
```bash
# Requires database setup and pytest
pytest test/test_f006_structure.py -v -s  # Individual pytest functions
pytest test/test_generic_ingest.py::test_f006_table_to_table_ingestion -v -s  # Full integration
```

## Key Differences from `ingest.py`

| Aspect | `ingest.py` (Raw SQL) | `f006.py` (ORM) |
|--------|----------------------|-----------------|
| **Database Interaction** | Raw SQL + parameters | SQLAlchemy ORM |
| **Error Handling** | Manual rollback | Automatic via ORM |
| **Relationships** | Manual FK management | Automatic via relationships |
| **Type Safety** | Runtime SQL errors | Compile-time type checking |
| **Maintainability** | Complex SQL strings | Python object methods |
| **Testing** | Requires full DB setup | Mockable components |

## Usage

### Direct Execution
```python
from ingestion.f006 import run_f006_ingestion
from quantdb.client import get_session

session = get_session(test=True)
result = run_f006_ingestion(session, commit=True)
```

### Dry Run (Testing)
```python
result = run_f006_ingestion(session, commit=False)  # Rollback transaction
```

## Integration with Generic Ingest

This implementation showcases the power of the `quantdb/generic_ingest.py` approach:

1. **`get_or_create()`** - Handles insert-or-update logic automatically
2. **`back_populate_tables()`** - Recursively resolves relationships
3. **`object_as_dict()`** - Converts ORM objects for constraint checking
4. **`query_by_constraints()`** - Finds existing records by unique constraints

## Future Enhancements

This foundation can be extended to include:
- Quantitative values (measurements)
- Categorical values (metadata)
- Complex relationships (parent-child hierarchies)
- Multiple data sources
- Real-time API integration

## Validation Results

```
✓ ALL STRUCTURE VALIDATION TESTS PASSED!
  - Data loading: 4 metadata entries
  - Path parsing: All paths correctly parsed
  - Dataset consistency: UUID and structure validated
  - Ingestion logic: 1 dataset + 4 packages + 5 instances

The F006 ingestion script is correctly structured and ready for testing.
```

This implementation proves that the generic_ingest approach can significantly simplify data ingestion while maintaining full functionality and improving maintainability.
