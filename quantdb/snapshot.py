"""Snapshot extraction for f006 gold-standard fixture data.

Queries the restored production database for all f006 data across all
tables and writes deterministic JSON fixture files:
  - Summary files for large tables (counts and breakdowns)
  - Full-row files for small tables (< 1000 rows)

Usage::

    from quantdb.snapshot import extract_f006_snapshot
    from quantdb.models import reflect_models

    models = reflect_models(engine=engine)
    session = models.Session()
    extract_f006_snapshot(session, Path('test/fixtures/f006'))
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session


F006_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'


def _write_json(path, data):
    """Write data to a JSON file with deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, sort_keys=True, default=str, indent=2)
        f.write('\n')


def _f006_object_uuids(session, models):
    """Return the set of object UUIDs linked to f006 via dataset_object."""
    DO = models.DatasetObject
    stmt = select(DO.object).where(DO.dataset == F006_UUID)
    return {str(row[0]) for row in session.execute(stmt).all()}


def _extract_values_inst_summary(session, models):
    """Extract values_inst summary: total count + breakdown by (type, desc_inst_label)."""
    VI = models.ValuesInst
    DI = models.DescriptorsInst

    # Total count
    total_stmt = (
        select(func.count())
        .select_from(VI)
        .where(VI.dataset == F006_UUID)
    )
    total = session.execute(total_stmt).scalar_one()

    # Breakdown by (type, desc_inst_label)
    breakdown_stmt = (
        select(VI.type, DI.label, func.count())
        .join(DI, VI.desc_inst == DI.id)
        .where(VI.dataset == F006_UUID)
        .group_by(VI.type, DI.label)
        .order_by(VI.type, DI.label)
    )
    rows = session.execute(breakdown_stmt).all()
    breakdown = {f"{row[0]}|{row[1]}": row[2] for row in rows}

    return {'total': total, 'breakdown': breakdown}


def _extract_values_quant_summary(session, models):
    """Extract values_quant summary: total count + per-descriptor-label breakdown."""
    VQ = models.ValuesQuant
    DQ = models.DescriptorsQuant
    DO = models.DatasetObject

    # Total count
    total_stmt = (
        select(func.count())
        .select_from(VQ)
        .join(DO, VQ.object == DO.object)
        .where(DO.dataset == F006_UUID)
    )
    total = session.execute(total_stmt).scalar_one()

    # Per-descriptor breakdown
    breakdown_stmt = (
        select(DQ.label, func.count())
        .select_from(VQ)
        .join(DQ, VQ.desc_quant == DQ.id)
        .join(DO, VQ.object == DO.object)
        .where(DO.dataset == F006_UUID)
        .group_by(DQ.label)
        .order_by(DQ.label)
    )
    rows = session.execute(breakdown_stmt).all()
    breakdown = {row[0]: row[1] for row in rows}

    return {'total': total, 'breakdown': breakdown}


def _extract_values_cat_summary(session, models):
    """Extract values_cat summary: total count + per-descriptor-label breakdown."""
    VC = models.ValuesCat
    DC = models.DescriptorsCat
    DO = models.DatasetObject

    # Total count
    total_stmt = (
        select(func.count())
        .select_from(VC)
        .join(DO, VC.object == DO.object)
        .where(DO.dataset == F006_UUID)
    )
    total = session.execute(total_stmt).scalar_one()

    # Per-descriptor breakdown
    breakdown_stmt = (
        select(DC.label, func.count())
        .select_from(VC)
        .join(DC, VC.desc_cat == DC.id)
        .join(DO, VC.object == DO.object)
        .where(DO.dataset == F006_UUID)
        .group_by(DC.label)
        .order_by(DC.label)
    )
    rows = session.execute(breakdown_stmt).all()
    breakdown = {row[0]: row[1] for row in rows}

    return {'total': total, 'breakdown': breakdown}


def _extract_instance_parent_count(session, models):
    """Extract instance_parent count for f006."""
    IP = models.InstanceParent
    VI = models.ValuesInst

    stmt = (
        select(func.count())
        .select_from(IP)
        .join(VI, IP.id == VI.id)
        .where(VI.dataset == F006_UUID)
    )
    count = session.execute(stmt).scalar_one()
    return {'total': count}


def _extract_dataset_object(session, models):
    """Extract all dataset_object rows for f006 (full rows)."""
    DO = models.DatasetObject
    stmt = (
        select(DO.dataset, DO.object)
        .where(DO.dataset == F006_UUID)
        .order_by(DO.object)
    )
    rows = session.execute(stmt).all()
    return [{'dataset': str(row[0]), 'object': str(row[1])} for row in rows]


def _extract_equiv_inst(session, models):
    """Extract all equiv_inst rows for f006 (full rows)."""
    EI = models.EquivInst
    VI = models.ValuesInst
    stmt = (
        select(EI.left_thing, EI.right_thing)
        .join(VI, EI.left_thing == VI.id)
        .where(VI.dataset == F006_UUID)
        .order_by(EI.left_thing, EI.right_thing)
    )
    rows = session.execute(stmt).all()
    return [{'left_thing': row[0], 'right_thing': row[1]} for row in rows]


def _extract_objects_internal(session, models):
    """Extract objects_internal rows for f006 (full rows)."""
    OI = models.ObjectsInternal
    stmt = (
        select(
            OI.id, OI.type, OI.dataset,
            OI.updated_transitive, OI.label, OI.curator_note,
        )
        .where(OI.dataset == F006_UUID)
        .order_by(OI.id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            'id': str(row[0]),
            'type': str(row[1]) if row[1] is not None else None,
            'dataset': str(row[2]) if row[2] is not None else None,
            'updated_transitive': str(row[3]) if row[3] is not None else None,
            'label': row[4],
            'curator_note': row[5],
        }
        for row in rows
    ]


def _extract_objects(session, models):
    """Extract all f006 objects (dataset object + linked objects)."""
    Obj = models.Objects
    DO = models.DatasetObject

    # Get object UUIDs linked to f006 + the dataset UUID itself
    linked_stmt = select(DO.object).where(DO.dataset == F006_UUID)
    linked = {row[0] for row in session.execute(linked_stmt).all()}
    all_ids = linked | {F006_UUID}

    stmt = (
        select(Obj.id, Obj.id_type, Obj.id_file, Obj.id_internal)
        .where(Obj.id.in_(all_ids))
        .order_by(Obj.id)
    )
    rows = session.execute(stmt).all()
    return [
        {
            'id': str(row[0]),
            'id_type': str(row[1]) if row[1] is not None else None,
            'id_file': row[2],
            'id_internal': str(row[3]) if row[3] is not None else None,
        }
        for row in rows
    ]


def _extract_obj_desc_inst(session, models):
    """Extract obj_desc_inst rows for f006 objects (full rows)."""
    ODI = models.ObjDescInst
    DO = models.DatasetObject

    object_uuids_stmt = select(DO.object).where(DO.dataset == F006_UUID)
    stmt = (
        select(
            ODI.object, ODI.desc_inst,
            ODI.addr_field, ODI.addr_desc_inst, ODI.expect,
        )
        .where(ODI.object.in_(object_uuids_stmt))
        .order_by(ODI.object, ODI.desc_inst)
    )
    rows = session.execute(stmt).all()
    return [
        {
            'object': str(row[0]),
            'desc_inst': row[1],
            'addr_field': row[2],
            'addr_desc_inst': row[3],
            'expect': row[4],
        }
        for row in rows
    ]


def _extract_obj_desc_quant(session, models):
    """Extract obj_desc_quant rows for f006 objects (full rows)."""
    ODQ = models.ObjDescQuant
    DO = models.DatasetObject

    object_uuids_stmt = select(DO.object).where(DO.dataset == F006_UUID)
    stmt = (
        select(
            ODQ.object, ODQ.desc_quant,
            ODQ.addr_field, ODQ.addr_unit, ODQ.addr_aspect,
            ODQ.addr_desc_inst, ODQ.expect,
        )
        .where(ODQ.object.in_(object_uuids_stmt))
        .order_by(ODQ.object, ODQ.desc_quant)
    )
    rows = session.execute(stmt).all()
    return [
        {
            'object': str(row[0]),
            'desc_quant': row[1],
            'addr_field': row[2],
            'addr_unit': row[3],
            'addr_aspect': row[4],
            'addr_desc_inst': row[5],
            'expect': row[6],
        }
        for row in rows
    ]


def _extract_obj_desc_cat(session, models):
    """Extract obj_desc_cat rows for f006 objects (full rows)."""
    ODC = models.ObjDescCat
    DO = models.DatasetObject

    object_uuids_stmt = select(DO.object).where(DO.dataset == F006_UUID)
    stmt = (
        select(
            ODC.object, ODC.desc_cat,
            ODC.addr_field, ODC.addr_desc_inst, ODC.expect,
        )
        .where(ODC.object.in_(object_uuids_stmt))
        .order_by(ODC.object, ODC.desc_cat)
    )
    rows = session.execute(stmt).all()
    return [
        {
            'object': str(row[0]),
            'desc_cat': row[1],
            'addr_field': row[2],
            'addr_desc_inst': row[3],
            'expect': row[4],
        }
        for row in rows
    ]


def extract_f006_snapshot(session, output_dir, models=None):
    """Extract all f006 data and write fixture JSON files.

    Creates summary files for large tables and full-row files for small
    tables.  Output is deterministic (sorted by PK, json.dumps with
    sort_keys=True).

    Args:
        session: A SQLAlchemy Session connected to the quantdb_test DB.
        output_dir: Path where fixture JSON files will be written.
        models: A ReflectedModels instance.  If None, will be reflected
                from the session's engine.

    Returns:
        Dict mapping filename to the data that was written.
    """
    if models is None:
        from quantdb.models import reflect_models
        models = reflect_models(engine=session.get_bind())

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures = {}

    # Summary files for large tables
    data = _extract_values_inst_summary(session, models)
    fixtures['values_inst_summary.json'] = data
    _write_json(output_dir / 'values_inst_summary.json', data)

    data = _extract_values_quant_summary(session, models)
    fixtures['values_quant_summary.json'] = data
    _write_json(output_dir / 'values_quant_summary.json', data)

    data = _extract_values_cat_summary(session, models)
    fixtures['values_cat_summary.json'] = data
    _write_json(output_dir / 'values_cat_summary.json', data)

    data = _extract_instance_parent_count(session, models)
    fixtures['instance_parent_count.json'] = data
    _write_json(output_dir / 'instance_parent_count.json', data)

    # Full-row files for small tables
    data = _extract_dataset_object(session, models)
    fixtures['dataset_object.json'] = data
    _write_json(output_dir / 'dataset_object.json', data)

    data = _extract_equiv_inst(session, models)
    fixtures['equiv_inst.json'] = data
    _write_json(output_dir / 'equiv_inst.json', data)

    data = _extract_objects_internal(session, models)
    fixtures['objects_internal.json'] = data
    _write_json(output_dir / 'objects_internal.json', data)

    data = _extract_objects(session, models)
    fixtures['objects.json'] = data
    _write_json(output_dir / 'objects.json', data)

    data = _extract_obj_desc_inst(session, models)
    fixtures['obj_desc_inst.json'] = data
    _write_json(output_dir / 'obj_desc_inst.json', data)

    data = _extract_obj_desc_quant(session, models)
    fixtures['obj_desc_quant.json'] = data
    _write_json(output_dir / 'obj_desc_quant.json', data)

    data = _extract_obj_desc_cat(session, models)
    fixtures['obj_desc_cat.json'] = data
    _write_json(output_dir / 'obj_desc_cat.json', data)

    return fixtures
