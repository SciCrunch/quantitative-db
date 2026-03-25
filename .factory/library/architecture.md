# Architecture

Architectural decisions, patterns discovered, and key design constraints.

**What belongs here:** Schema structure, FK dependency chain, trigger ordering, insert patterns.

---

## quantdb Schema (20 tables, 6 topo levels)

Level 0 (lookup): units, aspects, descriptors_inst, controlled_terms, addresses
Level 1: descriptors_quant, descriptors_cat (depend on units, aspects, descriptors_inst)
Level 2: objects_internal, objects (circular dep, broken at objects_internal -> objects)
Level 3: dataset_object, values_inst, obj_desc_inst (depend on objects)
Level 4: instance_parent, equiv_inst, class_parent, aspect_parent, obj_desc_quant, obj_desc_cat (depend on values_inst/obj_desc_inst)
Level 5: values_quant, values_cat (depend on obj_desc_quant/obj_desc_cat + values_inst + objects)

## Critical Trigger Ordering

For values_quant INSERT:
1. obj_desc_inst row must exist for (object, desc_inst) -- check_desc_inst_exists trigger
2. obj_desc_quant row must exist for (object, desc_quant) -- composite FK
3. values_inst row must exist for instance -- FK

For values_cat INSERT:
1. obj_desc_inst row must exist for (object, desc_inst) -- check_desc_inst_exists trigger
2. obj_desc_cat row must exist for (object, desc_cat) -- composite FK
3. values_inst row must exist for instance -- FK

deep_upsert() handles this automatically via _ensure_obj_desc_inst, _ensure_obj_desc_quant, _ensure_obj_desc_cat.

## FK-Safe Deletion Order (no CASCADE in schema)

Delete child-first:
1. values_quant, values_cat
2. obj_desc_quant, obj_desc_cat
3. obj_desc_inst
4. instance_parent, equiv_inst
5. values_inst
6. dataset_object
7. objects_internal
8. objects (only the non-dataset package objects)

## Ingest API Pattern

```python
from quantdb.generic_ingest import Ingest
from quantdb.models import reflect_models

models = reflect_models(engine=engine)
ing = Ingest(models)

with ing.session() as s:
    # FK columns accept string labels (auto-resolved to PKs)
    ing.row(s, 'values_quant',
        value=42.0, value_blob=42.0,
        object='<uuid>',          # str -> UUID passthrough
        desc_inst='nerve',         # str -> lookup by label
        desc_quant='count',        # str -> lookup by label
        instance={'dataset': '<uuid>', 'id_formal': 'sub-f006'})  # dict -> composite key lookup
```
