# Architecture

## System Overview

quantdb is a PostgreSQL database storing quantitative and categorical biomedical measurements with full provenance. The system has 20 tables across 6 topological levels in the `quantdb` schema.

## Core Data Flow

```
Source (Cassava/Pennsieve/CSV/GraphML)
  → Extraction (flat dicts with string FK labels)
  → Ingestion (FK resolution + parent-first insertion)
  → PostgreSQL quantdb schema
```

## Table Hierarchy

**Level 0 (Lookup, read-only):** units, aspects, descriptors_inst, controlled_terms, addresses
**Level 1 (Lookup):** descriptors_quant, descriptors_cat (depend on level-0)
**Level 2 (Data):** objects_internal, objects (circular FK)
**Level 3 (Data):** dataset_object, values_inst, obj_desc_inst
**Level 4 (Data/Hierarchy):** instance_parent, equiv_inst, class_parent, aspect_parent, obj_desc_quant, obj_desc_cat
**Level 5 (Data, largest):** values_quant, values_cat

## Key Relationships

- **objects**: Every entity (dataset, package, internal) registered here. UUID PK.
- **values_inst**: Instance hierarchy (subjects, samples, sites, fascicles). Each row has (dataset, id_formal, type, desc_inst).
- **instance_parent**: Parent-child links between values_inst rows.
- **values_quant/values_cat**: Actual measurements. Each ties (object, instance, descriptor) to a value.
- **obj_desc_***: Prerequisite "address" rows required before values inserts (enforced by triggers).

## Ingestion Pattern

1. Flat dicts use string labels for FK columns (auto-resolved by Ingest API)
2. Insertion follows FK-safe parent-first ordering
3. Deletion follows FK-safe child-first ordering
4. obj_desc_* prerequisites must be created before values
5. DISABLE TRIGGER USER for bulk inserts (AWS RDS compatible)
6. objects_internal has circular FK requiring constraint drop/re-add

## MicroCT Dataset Specifics

Dataset UUID: fb1cbd05-4320-4d8b-ac3a-44f1fe810718

Entity hierarchy:
```
subject (human, e.g., sub-SR001)
  → sample (nerve/nerve-volume, e.g., sam-SR001-CL1)
    → nerve structure (vagal trunk/branch/cranial nerve)
      → per-slice nerve cross-section
        → per-slice fascicle cross-section (from GraphML)
```

Data sources:
- NerveMorphology.csv: per-slice nerve measurements in pixels → convert to um/um2
- RawFascicleTracking.graphml: fascicle nodes (measurements) + edges (identity/split/merge)
- SummaryMorphology CSVs: aggregated stats in mm/mm2
- DataWrapper JSON: imaging metadata per sample
- Cassava: curation-export.json + path-metadata.json for entity/file metadata

Conversion factors: 1 pixel = 11.4 um (linear), 129.96 um2 (area)
