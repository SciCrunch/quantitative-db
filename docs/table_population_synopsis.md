# QuantDB Table Population Synopsis

## Quick Reference: Table Population Order

### 1. Root Tables (No Dependencies)
```
Addresses → Aspects → Units → ControlledTerms → DescriptorsInst → Objects
```

### 2. Intermediate Tables (Depend on Root)
```
DescriptorsCat → DescriptorsQuant → ValuesInst → ObjDescInst → ObjDescCat → ObjDescQuant
```

### 3. Leaf Tables (Use back_populate_tables)
```
ValuesCat, ValuesQuant
```

### 4. Self-Referencing Tables (After Base Records)
```
instance_parent, class_parent, aspect_parent, dataset_object, equiv_inst
```

## Key Hardcoded Values

### Required Enum Values
- **address_type**: `'constant'`, `'tabular-header'`, `'json-path-with-types'`
- **instance_type**: `'subject'`, `'sample'`, `'below'`
- **remote_id_type**: `'dataset'`, `'package'`
- **cat_range_type**: `'open'`, `'controlled'`
- **quant_agg_type**: `'instance'`, `'min'`, `'max'`, `'mean'`
- **quant_shape**: `'scalar'`

### ID Pattern Requirements
- Subject IDs: Must start with `'sub-'` (e.g., `'sub-001'`)
- Sample IDs: Must start with `'sam-'` (e.g., `'sam-001'`)

### Critical Constraints
1. **Objects**:
   - `id_type='package'` requires `id_file` to be set
   - `id_type='dataset'` cannot be used in `obj_desc_*` tables

2. **ValuesInst**:
   - `type='subject'`: `id_formal` = `id_sub`, `id_sam` = NULL
   - `type='sample'`: `id_formal` = `id_sam`

## Using back_populate_tables

### When to Use
- **Always** for leaf tables (ValuesCat, ValuesQuant)
- For complex intermediate tables with many relationships
- When you want automatic parent record creation

### How to Use
```python
# 1. Create your object
values_cat = ValuesCat(field1=value1, field2=value2, ...)

# 2. Set all relationships
values_cat.descriptors_inst = desc_inst_obj
values_cat.controlled_terms = term_obj
values_cat.objects = package_obj
# ... set all other relationships

# 3. Call back_populate_tables
result = back_populate_tables(session, values_cat)
```

### What It Does
1. Recursively traverses parent relationships
2. Creates missing parent records
3. Updates all foreign key references
4. Handles transaction safety

## Common Pitfalls to Avoid

1. **Wrong Population Order**: Always follow Root → Intermediate → Leaf order
2. **Missing Relationships**: Set ALL relationship properties before calling back_populate_tables
3. **Invalid IDs**: Ensure subject/sample IDs follow the required patterns
4. **Missing Required Fields**: Package objects need id_file, dataset objects don't
5. **Circular Dependencies**: Let back_populate_tables handle complex relationships

## Minimal Example

```python
from quantdb.generic_ingest import back_populate_tables, get_or_create

# Root tables
addr = get_or_create(session, Addresses(addr_type='constant', value_type='single'))
unit = get_or_create(session, Units(label='mm', iri='http://example.org/mm'))
aspect = get_or_create(session, Aspects(label='length', iri='http://example.org/length'))
desc_inst = get_or_create(session, DescriptorsInst(label='sample', iri='http://example.org/sample'))
dataset = get_or_create(session, Objects(id='dataset-uuid', id_type='dataset'))
package = get_or_create(session, Objects(id='package-uuid', id_type='package', id_file=123))

# Intermediate tables
desc_quant = get_or_create(session, DescriptorsQuant(
    unit=unit.id, aspect=aspect.id, domain=desc_inst.id,
    label='sample-length-mm', aggregation_type='instance', shape='scalar'
))
instance = get_or_create(session, ValuesInst(
    type='sample', desc_inst=desc_inst.id, dataset=dataset.id,
    id_formal='sam-001', id_sub='sub-001', id_sam='sam-001'
))
obj_desc_inst = get_or_create(session, ObjDescInst(
    object=package.id, desc_inst=desc_inst.id, addr_field=addr.id
))
obj_desc_quant = get_or_create(session, ObjDescQuant(
    object=package.id, desc_quant=desc_quant.id, addr_field=addr.id
))

# Leaf table with back_populate_tables
values_quant = ValuesQuant(
    value=10.5, object=package.id, desc_inst=desc_inst.id,
    desc_quant=desc_quant.id, instance=instance.id, value_blob={'value': 10.5}
)

# Set relationships
values_quant.descriptors_inst = desc_inst
values_quant.descriptors_quant = desc_quant
values_quant.values_inst = instance
values_quant.obj_desc_inst = obj_desc_inst
values_quant.obj_desc_quant = obj_desc_quant
values_quant.objects = package

# Let back_populate_tables handle everything
result = back_populate_tables(session, values_quant)
```

## Summary

The QuantDB schema enforces a strict hierarchy for data integrity:
1. **Root tables** provide the foundation (no dependencies)
2. **Intermediate tables** build relationships between roots
3. **Leaf tables** store actual measurement data (many dependencies)
4. **back_populate_tables** simplifies complex relationship management

Always populate tables in order, use back_populate_tables for leaf tables, and ensure all required fields and patterns are followed.
