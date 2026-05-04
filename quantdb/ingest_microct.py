"""MicroCT ingest pipeline: extract from DB, delete, and re-insert.

Follows the ``ingest_v2.py`` (f006) pattern for the REVA CD MicroCT
dataset (fb1cbd05-4320-4d8b-ac3a-44f1fe810718).

Functions
---------
extract_microct_from_db(session, models)
    Query the DB for all MicroCT data and convert each row to a flat
    dict with string FK labels.

delete_microct_data(session, models)
    Delete all MicroCT data in FK-safe child-first order without
    IntegrityError.

ingest_microct(session, models, data_dicts)
    Insert MicroCT data via ``Ingest.batch()`` for small tables and
    pre-resolved bulk SQL for large tables, in FK-safe parent-first
    order.
"""
from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.sql import text as sql_text

from quantdb.generic_ingest import Ingest

MICROCT_UUID = 'fb1cbd05-4320-4d8b-ac3a-44f1fe810718'

#: Default ``addresses.id`` for auto-created obj_desc_* rows.
#: id=1 is the ``(constant, '', single)`` address.
_DEFAULT_ADDR_FIELD = 1


# ---------------------------------------------------------------------------
# Extraction from DB
# ---------------------------------------------------------------------------


def extract_microct_from_db(session, models):
    """Extract all MicroCT data and convert to Ingest API flat-dict format.

    For FK integer columns (desc_inst, desc_quant, desc_cat, instance,
    etc.), resolves to the label/natural_key string by joining to the
    referenced table.  This produces dicts that ``Ingest.batch()`` can
    consume.

    Parameters
    ----------
    session : Session
        SQLAlchemy session connected to quantdb_test.
    models : ReflectedModels
        Reflected ORM models from ``reflect_models()``.

    Returns
    -------
    dict
        Keys: ``'objects'``, ``'dataset_object'``, ``'values_inst'``,
        ``'instance_parent'``, ``'values_quant'``, ``'values_cat'``.
        Each value is a list of flat dicts with string FK labels.
    """
    data = {}

    # --- objects ---
    Obj = models.Objects
    DO = models.DatasetObject

    linked_uuids = {row[0] for row in session.execute(select(DO.object).where(DO.dataset == MICROCT_UUID)).all()}
    all_obj_uuids = linked_uuids | {MICROCT_UUID}

    obj_stmt = select(Obj.id, Obj.id_type, Obj.id_file).where(Obj.id.in_(all_obj_uuids)).order_by(Obj.id)
    data['objects'] = [
        {
            'id': str(row[0]),
            'id_type': str(row[1]) if row[1] is not None else None,
            'id_file': row[2],
        }
        for row in session.execute(obj_stmt).all()
    ]

    # --- dataset_object ---
    do_stmt = select(DO.dataset, DO.object).where(DO.dataset == MICROCT_UUID).order_by(DO.object)
    data['dataset_object'] = [{'dataset': str(row[0]), 'object': str(row[1])} for row in session.execute(do_stmt).all()]

    # --- values_inst ---
    VI = models.ValuesInst
    DI = models.DescriptorsInst
    vi_stmt = (
        select(
            VI.dataset,
            VI.id_formal,
            VI.type,
            DI.label,
            VI.id_sub,
            VI.id_sam,
        )
        .join(DI, VI.desc_inst == DI.id)
        .where(VI.dataset == MICROCT_UUID)
        .order_by(VI.id)
    )
    data['values_inst'] = [
        {
            'dataset': str(row[0]),
            'id_formal': row[1],
            'type': str(row[2]),
            'desc_inst': row[3],
            'id_sub': row[4],
            'id_sam': row[5],
        }
        for row in session.execute(vi_stmt).all()
    ]

    # --- instance_parent ---
    ip_stmt = sql_text(
        """
        SELECT cv.id_formal AS child_formal,
               CAST(cv.dataset AS text) AS child_dataset,
               pv.id_formal AS parent_formal,
               CAST(pv.dataset AS text) AS parent_dataset
        FROM quantdb.instance_parent ip
        JOIN quantdb.values_inst cv ON ip.id = cv.id
        JOIN quantdb.values_inst pv ON ip.parent = pv.id
        WHERE cv.dataset = :uuid
        ORDER BY cv.id_formal
    """
    )
    data['instance_parent'] = [
        {
            'id': {
                'dataset': row[1],
                'id_formal': row[0],
            },
            'parent': {
                'dataset': row[3],
                'id_formal': row[2],
            },
        }
        for row in session.execute(ip_stmt, {'uuid': MICROCT_UUID}).all()
    ]

    # --- values_quant ---
    vq_stmt = sql_text(
        """
        SELECT vq.value, vq.value_blob,
               CAST(vq.object AS text) AS object,
               di.label AS desc_inst,
               dq.label AS desc_quant,
               CAST(vi.dataset AS text) AS inst_dataset,
               vi.id_formal AS inst_formal
        FROM quantdb.values_quant vq
        JOIN quantdb.descriptors_inst di ON vq.desc_inst = di.id
        JOIN quantdb.descriptors_quant dq ON vq.desc_quant = dq.id
        JOIN quantdb.values_inst vi ON vq.instance = vi.id
        WHERE vq.object IN (
            SELECT object FROM quantdb.dataset_object
            WHERE dataset = :uuid
        )
        ORDER BY vq.id
    """
    )
    data['values_quant'] = [
        {
            'value': float(row[0]) if row[0] is not None else None,
            'value_blob': row[1],
            'object': row[2],
            'desc_inst': row[3],
            'desc_quant': row[4],
            'instance': {
                'dataset': row[5],
                'id_formal': row[6],
            },
        }
        for row in session.execute(vq_stmt, {'uuid': MICROCT_UUID}).all()
    ]

    # --- values_cat ---
    vc_stmt = sql_text(
        """
        SELECT vc.value_open,
               ct.label AS value_controlled,
               CAST(vc.object AS text) AS object,
               di.label AS desc_inst,
               dc.label AS desc_cat,
               CAST(vi.dataset AS text) AS inst_dataset,
               vi.id_formal AS inst_formal
        FROM quantdb.values_cat vc
        JOIN quantdb.descriptors_inst di ON vc.desc_inst = di.id
        JOIN quantdb.descriptors_cat dc ON vc.desc_cat = dc.id
        LEFT JOIN quantdb.controlled_terms ct
            ON vc.value_controlled = ct.id
        JOIN quantdb.values_inst vi ON vc.instance = vi.id
        WHERE vc.object IN (
            SELECT object FROM quantdb.dataset_object
            WHERE dataset = :uuid
        )
        ORDER BY vc.id
    """
    )
    data['values_cat'] = [
        {
            'value_open': row[0],
            'value_controlled': row[1],
            'object': row[2],
            'desc_inst': row[3],
            'desc_cat': row[4],
            'instance': {
                'dataset': row[5],
                'id_formal': row[6],
            },
        }
        for row in session.execute(vc_stmt, {'uuid': MICROCT_UUID}).all()
    ]

    return data


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_microct_data(session, models):
    """Delete all MicroCT data in FK-safe child-first order.

    Deletion order (child-first to avoid IntegrityError):

    1. values_quant, values_cat
    2. obj_desc_quant, obj_desc_cat
    3. obj_desc_inst
    4. instance_parent
    5. values_inst
    6. dataset_object
    7. objects (package + dataset)

    Parameters
    ----------
    session : Session
        SQLAlchemy session connected to quantdb_test.
    models : ReflectedModels
        Reflected ORM models from ``reflect_models()``.
    """
    # Collect all MicroCT-related object UUIDs before deletion
    DO = models.DatasetObject

    linked_uuids = {row[0] for row in session.execute(select(DO.object).where(DO.dataset == MICROCT_UUID)).all()}
    all_obj_uuids = list(linked_uuids | {MICROCT_UUID})

    # Build subquery for all MicroCT objects (package only; no internals)
    _obj_subquery = """
        (SELECT object FROM quantdb.dataset_object WHERE dataset = :uuid)
    """

    # Disable triggers for faster bulk delete
    _disable_triggers = [
        'ALTER TABLE quantdb.values_quant DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.values_cat DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.obj_desc_quant DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.obj_desc_cat DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.obj_desc_inst DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.instance_parent DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.values_inst DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.dataset_object DISABLE TRIGGER USER',
        'ALTER TABLE quantdb.objects DISABLE TRIGGER USER',
    ]
    _enable_triggers = [s.replace('DISABLE', 'ENABLE') for s in _disable_triggers]

    for stmt in _disable_triggers:
        session.execute(sql_text(stmt))

    # Step 1: Delete values_quant and values_cat
    session.execute(
        sql_text('DELETE FROM quantdb.values_quant' f' WHERE object IN {_obj_subquery}'),
        {'uuid': MICROCT_UUID},
    )
    session.execute(
        sql_text('DELETE FROM quantdb.values_cat' f' WHERE object IN {_obj_subquery}'),
        {'uuid': MICROCT_UUID},
    )

    # Step 2: Delete obj_desc_quant, obj_desc_cat
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_quant' f' WHERE object IN {_obj_subquery}'),
        {'uuid': MICROCT_UUID},
    )
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_cat' f' WHERE object IN {_obj_subquery}'),
        {'uuid': MICROCT_UUID},
    )

    # Step 3: Delete obj_desc_inst
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_inst' f' WHERE object IN {_obj_subquery}'),
        {'uuid': MICROCT_UUID},
    )

    # Step 4: Delete instance_parent
    _inst_subquery = '(SELECT id FROM quantdb.values_inst WHERE dataset = :uuid)'
    session.execute(
        sql_text('DELETE FROM quantdb.instance_parent' f' WHERE id IN {_inst_subquery}'),
        {'uuid': MICROCT_UUID},
    )

    # Step 5: Delete values_inst
    session.execute(
        sql_text('DELETE FROM quantdb.values_inst WHERE dataset = :uuid'),
        {'uuid': MICROCT_UUID},
    )

    # Step 6: Delete dataset_object
    session.execute(
        sql_text('DELETE FROM quantdb.dataset_object WHERE dataset = :uuid'),
        {'uuid': MICROCT_UUID},
    )

    # Step 7: Delete remaining objects (package + dataset)
    if all_obj_uuids:
        session.execute(
            sql_text('DELETE FROM quantdb.objects WHERE id = ANY(:uuids)'),
            {'uuids': all_obj_uuids},
        )

    # Re-enable triggers
    for stmt in _enable_triggers:
        session.execute(sql_text(stmt))

    session.flush()


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _build_fk_lookups(session, models):
    """Build label -> id lookup dicts for FK resolution.

    Returns
    -------
    tuple
        (desc_inst_map, desc_quant_map, desc_cat_map, cterm_map)
        Each maps label string to integer PK.
    """
    DI = models.DescriptorsInst
    DQ = models.DescriptorsQuant
    DC = models.DescriptorsCat
    CT = models.ControlledTerms

    desc_inst_map = {row[1]: row[0] for row in session.execute(select(DI.id, DI.label)).all()}
    desc_quant_map = {row[1]: row[0] for row in session.execute(select(DQ.id, DQ.label)).all()}
    desc_cat_map = {row[1]: row[0] for row in session.execute(select(DC.id, DC.label)).all()}
    cterm_map = {row[1]: row[0] for row in session.execute(select(CT.id, CT.label)).all()}
    return desc_inst_map, desc_quant_map, desc_cat_map, cterm_map


def _build_instance_lookup(session):
    """Build (dataset_uuid, id_formal) -> values_inst.id lookup."""
    rows = session.execute(
        sql_text('SELECT id, CAST(dataset AS text), id_formal' ' FROM quantdb.values_inst' ' WHERE dataset = :uuid'),
        {'uuid': MICROCT_UUID},
    ).all()
    return {(row[1], row[2]): row[0] for row in rows}


def _collect_obj_desc_prerequisites(data_dicts, di_map, dq_map, dc_map):
    """Compute distinct (object, desc_inst/desc_quant/desc_cat) pairs.

    Returns
    -------
    tuple
        (odi_pairs, odq_pairs, odc_pairs)
        Each is a set of (object_uuid_str, descriptor_int_id) tuples.
    """
    odi_pairs = set()
    odq_pairs = set()
    odc_pairs = set()

    for vq in data_dicts.get('values_quant', []):
        obj = vq['object']
        di_id = di_map[vq['desc_inst']]
        dq_id = dq_map[vq['desc_quant']]
        odi_pairs.add((obj, di_id))
        odq_pairs.add((obj, dq_id))

    for vc in data_dicts.get('values_cat', []):
        obj = vc['object']
        di_id = di_map[vc['desc_inst']]
        dc_id = dc_map[vc['desc_cat']]
        odi_pairs.add((obj, di_id))
        odc_pairs.add((obj, dc_id))

    return odi_pairs, odq_pairs, odc_pairs


def ingest_microct(session, models, data_dicts):
    """Insert MicroCT data in FK-safe parent-first order.

    Uses ``Ingest.batch()`` for small tables (objects, dataset_object).
    Uses pre-resolved bulk SQL for large tables (values_inst,
    instance_parent, values_quant, values_cat).

    Insert ordering respects FK constraints and trigger prerequisites::

        objects -> dataset_object -> values_inst ->
        instance_parent -> obj_desc_inst ->
        obj_desc_quant -> obj_desc_cat -> values_quant -> values_cat

    Parameters
    ----------
    session : Session
        SQLAlchemy session connected to quantdb_test.
    models : ReflectedModels
        Reflected ORM models from ``reflect_models()``.
    data_dicts : dict
        Output from ``extract_microct_from_db()`` or from cassava
        extraction assembled into the same format.
    """
    ing = Ingest(models)

    # Build FK lookup maps (label -> id) for bulk resolution
    di_map, dq_map, dc_map, ct_map = _build_fk_lookups(session, models)

    # ------------------------------------------------------------------
    # Step 1: Insert objects (small, Ingest.batch())
    # ------------------------------------------------------------------
    if data_dicts.get('objects'):
        ing.batch(session, 'objects', data_dicts['objects'])
        session.flush()

    # ------------------------------------------------------------------
    # Step 2: Insert dataset_object (small, Ingest.batch())
    # ------------------------------------------------------------------
    if data_dicts.get('dataset_object'):
        ing.batch(session, 'dataset_object', data_dicts['dataset_object'])
        session.flush()

    # ------------------------------------------------------------------
    # Step 3: Insert values_inst (bulk insert)
    # ------------------------------------------------------------------
    vi_rows = data_dicts.get('values_inst', [])
    if vi_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_inst DISABLE TRIGGER USER'))

        resolved_vi = [
            {
                'dataset': vi['dataset'],
                'id_formal': vi['id_formal'],
                'type': vi['type'],
                'desc_inst': di_map[vi['desc_inst']],
                'id_sub': vi.get('id_sub'),
                'id_sam': vi.get('id_sam'),
            }
            for vi in vi_rows
        ]
        vi_table = models.ValuesInst.__table__
        session.execute(insert(vi_table), resolved_vi)

        session.execute(sql_text('ALTER TABLE quantdb.values_inst ENABLE TRIGGER USER'))
        session.flush()

    # Build instance lookup: (dataset_uuid, id_formal) -> int id
    inst_lookup = _build_instance_lookup(session)

    # ------------------------------------------------------------------
    # Step 4: Insert instance_parent (bulk insert)
    # ------------------------------------------------------------------
    ip_rows = data_dicts.get('instance_parent', [])
    if ip_rows:
        session.execute(sql_text('ALTER TABLE quantdb.instance_parent' ' DISABLE TRIGGER USER'))

        resolved_ip = [
            {
                'id': inst_lookup[(ip['id']['dataset'], ip['id']['id_formal'])],
                'parent': inst_lookup[
                    (
                        ip['parent']['dataset'],
                        ip['parent']['id_formal'],
                    )
                ],
            }
            for ip in ip_rows
        ]
        ip_table = models.InstanceParent.__table__
        session.execute(insert(ip_table), resolved_ip)

        session.execute(sql_text('ALTER TABLE quantdb.instance_parent' ' ENABLE TRIGGER USER'))
        session.flush()

    # ------------------------------------------------------------------
    # Step 5: Pre-create obj_desc_* prerequisite rows (bulk SQL)
    # ------------------------------------------------------------------
    odi_pairs, odq_pairs, odc_pairs = _collect_obj_desc_prerequisites(
        data_dicts,
        di_map,
        dq_map,
        dc_map,
    )

    if odi_pairs:
        odi_dicts = [
            {
                'object': obj,
                'desc_inst': di,
                'addr_field': _DEFAULT_ADDR_FIELD,
            }
            for obj, di in odi_pairs
        ]
        session.execute(
            sql_text(
                'INSERT INTO quantdb.obj_desc_inst'
                ' (object, desc_inst, addr_field)'
                ' VALUES (:object, :desc_inst, :addr_field)'
                ' ON CONFLICT DO NOTHING'
            ),
            odi_dicts,
        )
        session.flush()

    if odq_pairs:
        odq_dicts = [
            {
                'object': obj,
                'desc_quant': dq,
                'addr_field': _DEFAULT_ADDR_FIELD,
            }
            for obj, dq in odq_pairs
        ]
        session.execute(
            sql_text(
                'INSERT INTO quantdb.obj_desc_quant'
                ' (object, desc_quant, addr_field)'
                ' VALUES (:object, :desc_quant, :addr_field)'
                ' ON CONFLICT DO NOTHING'
            ),
            odq_dicts,
        )
        session.flush()

    if odc_pairs:
        odc_dicts = [
            {
                'object': obj,
                'desc_cat': dc,
                'addr_field': _DEFAULT_ADDR_FIELD,
            }
            for obj, dc in odc_pairs
        ]
        session.execute(
            sql_text(
                'INSERT INTO quantdb.obj_desc_cat'
                ' (object, desc_cat, addr_field)'
                ' VALUES (:object, :desc_cat, :addr_field)'
                ' ON CONFLICT DO NOTHING'
            ),
            odc_dicts,
        )
        session.flush()

    # ------------------------------------------------------------------
    # Step 6: Insert values_quant (bulk insert)
    # ------------------------------------------------------------------
    vq_rows = data_dicts.get('values_quant', [])
    if vq_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_quant DISABLE TRIGGER USER'))

        resolved_vq = [
            {
                'value': vq['value'],
                'value_blob': vq['value_blob'],
                'object': vq['object'],
                'desc_inst': di_map[vq['desc_inst']],
                'desc_quant': dq_map[vq['desc_quant']],
                'instance': inst_lookup[
                    (
                        vq['instance']['dataset'],
                        vq['instance']['id_formal'],
                    )
                ],
            }
            for vq in vq_rows
        ]
        vq_table = models.ValuesQuant.__table__
        session.execute(insert(vq_table), resolved_vq)

        session.execute(sql_text('ALTER TABLE quantdb.values_quant ENABLE TRIGGER USER'))
        session.flush()

    # ------------------------------------------------------------------
    # Step 7: Insert values_cat (bulk insert)
    # ------------------------------------------------------------------
    vc_rows = data_dicts.get('values_cat', [])
    if vc_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_cat DISABLE TRIGGER USER'))

        resolved_vc = [
            {
                'value_open': vc['value_open'],
                'value_controlled': (
                    ct_map[vc['value_controlled']] if vc.get('value_controlled') is not None else None
                ),
                'object': vc['object'],
                'desc_inst': di_map[vc['desc_inst']],
                'desc_cat': dc_map[vc['desc_cat']],
                'instance': inst_lookup[
                    (
                        vc['instance']['dataset'],
                        vc['instance']['id_formal'],
                    )
                ],
            }
            for vc in vc_rows
        ]
        vc_table = models.ValuesCat.__table__
        session.execute(insert(vc_table), resolved_vc)

        session.execute(sql_text('ALTER TABLE quantdb.values_cat ENABLE TRIGGER USER'))
        session.flush()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def _count_microct(session, models):
    """Return a dict of MicroCT row counts for all data tables."""
    counts = {}

    VI = models.ValuesInst
    counts['values_inst'] = session.execute(
        select(func.count()).select_from(VI).where(VI.dataset == MICROCT_UUID)
    ).scalar_one()

    DO = models.DatasetObject
    counts['dataset_object'] = session.execute(
        select(func.count()).select_from(DO).where(DO.dataset == MICROCT_UUID)
    ).scalar_one()

    IP = models.InstanceParent
    counts['instance_parent'] = session.execute(
        select(func.count()).select_from(IP).join(VI, IP.id == VI.id).where(VI.dataset == MICROCT_UUID)
    ).scalar_one()

    Obj = models.Objects
    obj_sub = select(DO.object).where(DO.dataset == MICROCT_UUID)
    # Count objects: dataset_object objects + dataset itself
    counts['objects'] = session.execute(
        select(func.count())
        .select_from(Obj)
        .where(Obj.id.in_(obj_sub.union(select(DO.dataset).where(DO.dataset == MICROCT_UUID))))
    ).scalar_one()

    VQ = models.ValuesQuant
    counts['values_quant'] = session.execute(
        select(func.count()).select_from(VQ).join(DO, VQ.object == DO.object).where(DO.dataset == MICROCT_UUID)
    ).scalar_one()

    VC = models.ValuesCat
    counts['values_cat'] = session.execute(
        select(func.count()).select_from(VC).join(DO, VC.object == DO.object).where(DO.dataset == MICROCT_UUID)
    ).scalar_one()

    ODI = models.ObjDescInst
    counts['obj_desc_inst'] = session.execute(
        select(func.count()).select_from(ODI).where(ODI.object.in_(obj_sub))
    ).scalar_one()

    ODQ = models.ObjDescQuant
    counts['obj_desc_quant'] = session.execute(
        select(func.count()).select_from(ODQ).where(ODQ.object.in_(obj_sub))
    ).scalar_one()

    ODC = models.ObjDescCat
    counts['obj_desc_cat'] = session.execute(
        select(func.count()).select_from(ODC).where(ODC.object.in_(obj_sub))
    ).scalar_one()

    return counts
