"""Snapshot extraction and comparison for f006 gold-standard fixture data.

Queries the restored production database for all f006 data across all
tables and writes deterministic JSON fixture files:
  - Summary files for large tables (counts and breakdowns)
  - Full-row files for small tables (< 1000 rows)

Also provides comparison utilities that diff current DB state against
fixture files and return structured results.

Usage::

    from quantdb.snapshot import extract_f006_snapshot, compare_snapshot
    from quantdb.models import reflect_models

    models = reflect_models(engine=engine)
    session = models.Session()

    # Extract fixtures
    extract_f006_snapshot(session, Path('test/fixtures/f006'))

    # Compare DB state against fixtures
    result = compare_snapshot(session, Path('test/fixtures/f006'))
    if not result.is_identical:
        for name, diff in result.tables.items():
            if not diff.is_match:
                print(f'{name}: {diff}')
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Comparison utilities
# ---------------------------------------------------------------------------


@dataclass
class TableDiff:
    """Diff result for a single table comparison.

    For summary tables (values_inst_summary, etc.), the count and
    breakdown fields are populated.  For full-row tables (dataset_object,
    etc.), the row_count, added, removed, and modified fields are used.

    Attributes:
        table: Table/fixture name (without .json extension).
        fixture_type: ``'summary'`` or ``'full_rows'``.
        is_match: True if no differences were detected.
        count_expected: Fixture total count (summary tables only).
        count_actual: DB total count (summary tables only).
        breakdown_added: Breakdown keys present in DB but not in fixture.
        breakdown_removed: Breakdown keys present in fixture but not in DB.
        breakdown_changed: Keys where fixture and DB counts differ.
        row_count_expected: Fixture row count (full-row tables only).
        row_count_actual: DB row count (full-row tables only).
        added: Rows present in DB but not in fixture.
        removed: Rows present in fixture but not in DB.
        modified: Rows with matching PK but different non-PK values.
    """
    table: str
    fixture_type: str
    is_match: bool = True
    # Summary fields
    count_expected: int | None = None
    count_actual: int | None = None
    breakdown_added: dict = field(default_factory=dict)
    breakdown_removed: dict = field(default_factory=dict)
    breakdown_changed: dict = field(default_factory=dict)
    # Full-row fields
    row_count_expected: int | None = None
    row_count_actual: int | None = None
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    modified: list = field(default_factory=list)


@dataclass
class SnapshotDiff:
    """Overall comparison result across all f006 fixture tables.

    Attributes:
        is_identical: True if every table comparison matched.
        tables: Mapping of table name to its :class:`TableDiff`.
    """
    is_identical: bool = True
    tables: dict = field(default_factory=dict)


# Mapping of summary fixture names to their extraction functions.
_SUMMARY_TABLES = {
    'values_inst_summary': _extract_values_inst_summary,
    'values_quant_summary': _extract_values_quant_summary,
    'values_cat_summary': _extract_values_cat_summary,
    'instance_parent_count': _extract_instance_parent_count,
}

# Mapping of full-row fixture names to (extraction_fn, pk_columns).
_FULL_ROW_TABLES = {
    'dataset_object': (_extract_dataset_object, ('dataset', 'object')),
    'equiv_inst': (_extract_equiv_inst, ('left_thing', 'right_thing')),
    'objects_internal': (_extract_objects_internal, ('id',)),
    'objects': (_extract_objects, ('id',)),
    'obj_desc_inst': (_extract_obj_desc_inst, ('object', 'desc_inst')),
    'obj_desc_quant': (_extract_obj_desc_quant, ('object', 'desc_quant')),
    'obj_desc_cat': (_extract_obj_desc_cat, ('object', 'desc_cat')),
}


def _compare_summary(table_name, fixture_data, db_data):
    """Compare a summary fixture against current DB data.

    Returns a :class:`TableDiff` with count and breakdown differences.
    """
    diff = TableDiff(table=table_name, fixture_type='summary')

    diff.count_expected = fixture_data.get('total', 0)
    diff.count_actual = db_data.get('total', 0)

    fix_bd = fixture_data.get('breakdown', {})
    db_bd = db_data.get('breakdown', {})

    for key in sorted(set(db_bd) - set(fix_bd)):
        diff.breakdown_added[key] = db_bd[key]
    for key in sorted(set(fix_bd) - set(db_bd)):
        diff.breakdown_removed[key] = fix_bd[key]
    for key in sorted(set(fix_bd) & set(db_bd)):
        if fix_bd[key] != db_bd[key]:
            diff.breakdown_changed[key] = {
                'expected': fix_bd[key],
                'actual': db_bd[key],
            }

    if (diff.count_expected != diff.count_actual
            or diff.breakdown_added
            or diff.breakdown_removed
            or diff.breakdown_changed):
        diff.is_match = False

    return diff


def _row_key(row, pk_cols):
    """Build a hashable key from a row dict using the given PK columns."""
    return tuple(str(row[col]) for col in pk_cols)


def _compare_full_rows(table_name, fixture_rows, db_rows, pk_cols):
    """Compare a full-row fixture against current DB rows.

    Returns a :class:`TableDiff` with added, removed, and modified rows.
    """
    diff = TableDiff(table=table_name, fixture_type='full_rows')
    diff.row_count_expected = len(fixture_rows)
    diff.row_count_actual = len(db_rows)

    fix_dict = {_row_key(r, pk_cols): r for r in fixture_rows}
    db_dict = {_row_key(r, pk_cols): r for r in db_rows}

    fix_keys = set(fix_dict)
    db_keys = set(db_dict)

    # Added: rows in DB not in fixture
    for key in sorted(db_keys - fix_keys):
        diff.added.append(db_dict[key])

    # Removed: rows in fixture not in DB
    for key in sorted(fix_keys - db_keys):
        diff.removed.append(fix_dict[key])

    # Modified: same PK, different non-PK values
    for key in sorted(fix_keys & db_keys):
        fix_row = fix_dict[key]
        db_row = db_dict[key]
        changes = {}
        for col in fix_row:
            if col in pk_cols:
                continue
            fix_val = fix_row.get(col)
            db_val = db_row.get(col)
            if str(fix_val) != str(db_val):
                changes[col] = {'expected': fix_val, 'actual': db_val}
        if changes:
            pk_dict = {col: fix_row[col] for col in pk_cols}
            diff.modified.append({'pk': pk_dict, 'changes': changes})

    if diff.added or diff.removed or diff.modified:
        diff.is_match = False

    return diff


def compare_snapshot(session, fixtures_dir, models=None):
    """Compare current DB state for f006 against fixture files.

    Loads each fixture JSON file from *fixtures_dir*, queries the
    corresponding data from the database via *session*, and returns a
    structured :class:`SnapshotDiff` with per-table diff info.

    Args:
        session: A SQLAlchemy Session connected to the quantdb_test DB.
        fixtures_dir: Path to the directory containing fixture JSON files.
        models: A ReflectedModels instance.  If None, will be reflected
                from the session's engine.

    Returns:
        A :class:`SnapshotDiff` with ``is_identical`` flag and per-table
        ``TableDiff`` entries.
    """
    if models is None:
        from quantdb.models import reflect_models
        models = reflect_models(engine=session.get_bind())

    fixtures_dir = Path(fixtures_dir)
    result = SnapshotDiff()

    # Compare summary tables
    for name, extract_fn in _SUMMARY_TABLES.items():
        fixture_path = fixtures_dir / f'{name}.json'
        if not fixture_path.exists():
            continue
        with open(fixture_path) as f:
            fixture_data = json.load(f)
        db_data = extract_fn(session, models)
        diff = _compare_summary(name, fixture_data, db_data)
        result.tables[name] = diff
        if not diff.is_match:
            result.is_identical = False

    # Compare full-row tables
    for name, (extract_fn, pk_cols) in _FULL_ROW_TABLES.items():
        fixture_path = fixtures_dir / f'{name}.json'
        if not fixture_path.exists():
            continue
        with open(fixture_path) as f:
            fixture_rows = json.load(f)
        db_rows = extract_fn(session, models)
        diff = _compare_full_rows(name, fixture_rows, db_rows, pk_cols)
        result.tables[name] = diff
        if not diff.is_match:
            result.is_identical = False

    return result
