# QuantDB Table Population Guide

This guide explains the correct order for populating tables in the QuantDB schema and how to use the `back_populate_tables` function for leaf tables.

## Table Hierarchy Overview

The QuantDB schema consists of four levels of tables:

1. **Root Tables** - No dependencies on other tables
2. **Intermediate Tables** - Depend on root tables
3. **Leaf Tables** - Depend on many other tables
4. **Self-Referencing Tables** - Reference themselves for hierarchical relationships

## 1. Root Tables (Populate First)

These tables have no foreign key dependencies and must be populated first:

### Addresses
- **Purpose**: Store data source locations and extraction methods
- **Key Fields**: `addr_type`, `addr_field`, `value_type`
- **Example Values**:
  ```python
  Addresses(addr_type='constant', addr_field=None, value_type='single')
  Addresses(addr_type='tabular-header', addr_field='diameter', value_type='single')
  Addresses(addr_type='json-path-with-types', addr_field='#/data/#int/value', value_type='multi')
  ```

### Aspects
- **Purpose**: Define measurement aspects (what is being measured)
- **Key Fields**: `label`, `iri`
- **Example Values**:
  ```python
  Aspects(label='distance', iri='http://uri.interlex.org/aspect/distance')
  Aspects(label='diameter', iri='http://uri.interlex.org/aspect/diameter')
  ```

### Units
- **Purpose**: Define measurement units
- **Key Fields**: `label`, `iri`
- **Example Values**:
  ```python
  Units(label='mm', iri='http://uri.interlex.org/unit/millimeter')
  Units(label='um', iri='http://uri.interlex.org/unit/micrometer')
  ```

### ControlledTerms
- **Purpose**: Controlled vocabulary for categorical values
- **Key Fields**: `label`, `iri`
- **Example Values**:
  ```python
  ControlledTerms(label='microct', iri='http://uri.interlex.org/controlled/microct')
  ControlledTerms(label='human', iri='http://uri.interlex.org/controlled/human')
  ```

### DescriptorsInst
- **Purpose**: Instance class descriptors (types of things being measured)
- **Key Fields**: `label`, `iri`
- **Example Values**:
  ```python
  DescriptorsInst(label='human', iri='http://uri.interlex.org/class/human')
  DescriptorsInst(label='nerve-volume', iri='http://uri.interlex.org/class/nerve-volume')
  ```

### Objects
- **Purpose**: Data objects (datasets, packages)
- **Key Fields**: `id`, `id_type`, `id_file`
- **Constraints**:
  - `id_type='package'` requires `id_file` to be set
  - `id_type='quantdb'` requires `id_internal` to be set
- **Example Values**:
  ```python
  Objects(id='uuid-here', id_type='dataset')
  Objects(id='uuid-here', id_type='package', id_file=12345)
  ```

## 2. Intermediate Tables (Populate Second)

These tables depend on root tables:

### DescriptorsCat
- **Purpose**: Categorical descriptors (properties that can have categorical values)
- **Dependencies**: DescriptorsInst (for domain)
- **Example**:
  ```python
  DescriptorsCat(
      domain=desc_inst_id,  # From DescriptorsInst
      range='controlled',   # or 'open'
      label='hasModality'
  )
  ```

### DescriptorsQuant
- **Purpose**: Quantitative descriptors (measurable properties)
- **Dependencies**: Units, Aspects, DescriptorsInst (for domain)
- **Example**:
  ```python
  DescriptorsQuant(
      shape='scalar',
      label='nerve-diameter-um',
      aggregation_type='instance',
      unit=unit_id,        # From Units
      aspect=aspect_id,    # From Aspects
      domain=desc_inst_id  # From DescriptorsInst
  )
  ```

### ValuesInst
- **Purpose**: Instance values (subjects, samples, etc.)
- **Dependencies**: Objects (dataset), DescriptorsInst
- **Constraints**:
  - Subject IDs must match `^sub-` pattern
  - Sample IDs must match `^sam-` pattern
  - For `type='subject'`: `id_formal` must equal `id_sub`, `id_sam` must be NULL
  - For `type='sample'`: `id_formal` must equal `id_sam`
- **Example**:
  ```python
  # Subject
  ValuesInst(
      type='subject',
      desc_inst=human_desc_id,
      dataset=dataset_uuid,
      id_formal='sub-001',
      id_sub='sub-001',
      id_sam=None
  )

  # Sample
  ValuesInst(
      type='sample',
      desc_inst=sample_desc_id,
      dataset=dataset_uuid,
      id_formal='sam-001',
      id_sub='sub-001',
      id_sam='sam-001'
  )
  ```

### ObjDescInst
- **Purpose**: Maps objects to instance descriptors
- **Dependencies**: Objects, DescriptorsInst, Addresses
- **Example**:
  ```python
  ObjDescInst(
      object=package_uuid,
      desc_inst=desc_inst_id,
      addr_field=address_id
  )
  ```

### ObjDescCat
- **Purpose**: Maps objects to categorical descriptors
- **Dependencies**: Objects, DescriptorsCat, Addresses
- **Example**:
  ```python
  ObjDescCat(
      object=package_uuid,
      desc_cat=desc_cat_id,
      addr_field=address_id
  )
  ```

### ObjDescQuant
- **Purpose**: Maps objects to quantitative descriptors
- **Dependencies**: Objects, DescriptorsQuant, Addresses
- **Example**:
  ```python
  ObjDescQuant(
      object=package_uuid,
      desc_quant=desc_quant_id,
      addr_field=address_id
  )
  ```

## 3. Leaf Tables (Populate Last)

These tables depend on many other tables and should use `back_populate_tables`:

### ValuesCat
- **Purpose**: Store categorical measurement values
- **Dependencies**: Objects, DescriptorsInst, DescriptorsCat, ValuesInst, ObjDescCat, ObjDescInst, ControlledTerms
- **Example with back_populate_tables**:
  ```python
  # Create the object with relationships
  values_cat = ValuesCat(
      value_open='some-value',
      value_controlled=controlled_term_id,
      object=package_uuid,
      desc_inst=desc_inst_id,
      desc_cat=desc_cat_id,
      instance=instance_id
  )

  # Set relationships
  values_cat.controlled_terms = controlled_term_obj
  values_cat.descriptors_cat = desc_cat_obj
  values_cat.descriptors_inst = desc_inst_obj
  values_cat.values_inst = values_inst_obj
  values_cat.obj_desc_cat = obj_desc_cat_obj
  values_cat.obj_desc_inst = obj_desc_inst_obj
  values_cat.objects = objects_obj

  # Use back_populate_tables to handle all relationships
  result = back_populate_tables(session, values_cat)
  ```

### ValuesQuant
- **Purpose**: Store quantitative measurement values
- **Dependencies**: Objects, DescriptorsInst, DescriptorsQuant, ValuesInst, ObjDescInst, ObjDescQuant
- **Example with back_populate_tables**:
  ```python
  # Create the object with relationships
  values_quant = ValuesQuant(
      value=42.5,
      object=package_uuid,
      desc_inst=desc_inst_id,
      desc_quant=desc_quant_id,
      instance=instance_id,
      value_blob={'value': 42.5, 'unit': 'mm'}
  )

  # Set relationships
  values_quant.descriptors_inst = desc_inst_obj
  values_quant.descriptors_quant = desc_quant_obj
  values_quant.values_inst = values_inst_obj
  values_quant.obj_desc_inst = obj_desc_inst_obj
  values_quant.obj_desc_quant = obj_desc_quant_obj
  values_quant.objects = objects_obj

  # Use back_populate_tables to handle all relationships
  result = back_populate_tables(session, values_quant)
  ```

## 4. Self-Referencing Tables

These tables can be populated after their base records exist:

- **instance_parent**: Parent-child relationships for ValuesInst
- **class_parent**: Parent-child relationships for DescriptorsInst
- **aspect_parent**: Parent-child relationships for Aspects
- **dataset_object**: Links datasets to their objects
- **equiv_inst**: Equivalent instances

## Using back_populate_tables

The `back_populate_tables` function is essential for handling complex relationships in leaf tables:

### Benefits:
1. **Automatic Parent Creation**: Creates missing parent records automatically
2. **Relationship Management**: Handles complex webs of foreign key relationships
3. **Recursive Population**: Recursively populates all parent tables
4. **Transaction Safety**: Handles rollbacks on errors

### How it Works:
1. Traverses all MANYTOONE and MANYTOMANY relationships
2. Checks if parent objects exist in the database
3. Creates missing parents recursively
4. Updates foreign key references
5. Commits the final object with all relationships

### Best Practices:
1. Create your leaf table object with all required fields
2. Set all relationship properties to their corresponding objects
3. Call `back_populate_tables(session, object)`
4. The function will handle all the complexity

## Hardcoded Values and Constraints

### Enum Values:
- **address_type**: `'constant'`, `'tabular-header'`, `'json-path-with-types'`, etc.
- **cat_range_type**: `'open'`, `'controlled'`
- **instance_type**: `'subject'`, `'sample'`, `'below'`
- **remote_id_type**: `'dataset'`, `'package'`, `'collection'`, `'organization'`, `'quantdb'`
- **quant_agg_type**: `'instance'`, `'min'`, `'max'`, `'mean'`, `'sum'`, etc.
- **quant_shape**: `'scalar'`
- **field_value_type**: `'single'`, `'multi'`

### ID Pattern Constraints:
- Subject IDs: Must match `^sub-` (e.g., `'sub-001'`)
- Sample IDs: Must match `^sam-` (e.g., `'sam-001'`)

### Object Type Constraints:
- `id_type='package'` requires `id_file` to be set
- `id_type='quantdb'` requires `id_internal` to be set
- Dataset objects cannot be used in `obj_desc_*` tables

## Example: Complete Ingestion Flow

```python
from quantdb.generic_ingest import back_populate_tables, get_or_create
from quantdb.models import *

# 1. Create root data
addr = get_or_create(session, Addresses(addr_type='constant', value_type='single'))
aspect = get_or_create(session, Aspects(label='diameter', iri='http://...'))
unit = get_or_create(session, Units(label='mm', iri='http://...'))
term = get_or_create(session, ControlledTerms(label='microct', iri='http://...'))
desc_inst = get_or_create(session, DescriptorsInst(label='sample', iri='http://...'))
dataset = get_or_create(session, Objects(id='uuid', id_type='dataset'))
package = get_or_create(session, Objects(id='uuid', id_type='package', id_file=123))

# 2. Create intermediate data
desc_cat = get_or_create(session, DescriptorsCat(
    domain=desc_inst.id, range='controlled', label='modality'
))
desc_quant = get_or_create(session, DescriptorsQuant(
    unit=unit.id, aspect=aspect.id, domain=desc_inst.id,
    label='sample-diameter', aggregation_type='instance'
))
instance = get_or_create(session, ValuesInst(
    type='sample', desc_inst=desc_inst.id, dataset=dataset.id,
    id_formal='sam-001', id_sub='sub-001', id_sam='sam-001'
))

# 3. Create mappings
obj_desc_inst = get_or_create(session, ObjDescInst(
    object=package.id, desc_inst=desc_inst.id, addr_field=addr.id
))
obj_desc_cat = get_or_create(session, ObjDescCat(
    object=package.id, desc_cat=desc_cat.id, addr_field=addr.id
))
obj_desc_quant = get_or_create(session, ObjDescQuant(
    object=package.id, desc_quant=desc_quant.id, addr_field=addr.id
))

# 4. Create leaf data with back_populate_tables
values_cat = ValuesCat(
    value_controlled=term.id,
    object=package.id,
    desc_inst=desc_inst.id,
    desc_cat=desc_cat.id,
    instance=instance.id
)
# Set all relationships
values_cat.controlled_terms = term
values_cat.descriptors_cat = desc_cat
values_cat.descriptors_inst = desc_inst
values_cat.values_inst = instance
values_cat.obj_desc_cat = obj_desc_cat
values_cat.obj_desc_inst = obj_desc_inst
values_cat.objects = package

# Let back_populate_tables handle everything
result = back_populate_tables(session, values_cat)
```

This approach ensures data integrity and proper relationship management throughout the ingestion process.
