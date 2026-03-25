"""V2 ingest pipeline: dump-based extract, delete, and re-insert for f006.

Extracts f006 data from the production-dump-restored DB, converts rows
to Ingest API flat-dict format with string FK labels, deletes f006 data
in FK-safe order, and re-inserts via ``Ingest.batch()`` for small tables
and bulk SQL for large tables.

Functions
---------
extract_f006_from_db(session, models)
    Query the restored production DB for all f006 data and convert each
    row to a flat dict with string FK labels.

delete_f006_data(session, models)
    Delete all f006 data in FK-safe child-first order without
    IntegrityError.

ingest_f006_v2(session, models, data_dicts)
    Insert f006 data via ``Ingest.batch()`` for small tables and
    pre-resolved bulk SQL for large tables, in FK-safe parent-first
    order.
"""
from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.sql import text as sql_text

from quantdb.generic_ingest import Ingest

F006_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'

#: Default ``addresses.id`` for auto-created obj_desc_* rows.
#: id=1 is the ``(constant, '', single)`` address.
_DEFAULT_ADDR_FIELD = 1


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_f006_from_db(session, models):
    """Extract all f006 data and convert to Ingest API flat-dict format.

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
        Keys: ``'objects'``, ``'objects_internal'``, ``'dataset_object'``,
        ``'values_inst'``, ``'instance_parent'``, ``'equiv_inst'``,
        ``'values_quant'``, ``'values_cat'``.
        Each value is a list of flat dicts with string FK labels.
    """
    data = {}

    # --- objects ---
    Obj = models.Objects
    DO = models.DatasetObject
    OI = models.ObjectsInternal

    # Collect all f006-related object UUIDs
    linked_uuids = {row[0] for row in session.execute(select(DO.object).where(DO.dataset == F006_UUID)).all()}
    internal_uuids = {row[0] for row in session.execute(select(OI.id).where(OI.dataset == F006_UUID)).all()}
    all_obj_uuids = linked_uuids | internal_uuids | {F006_UUID}

    obj_stmt = select(Obj.id, Obj.id_type, Obj.id_file).where(Obj.id.in_(all_obj_uuids)).order_by(Obj.id)
    data['objects'] = [
        {
            'id': str(row[0]),
            'id_type': str(row[1]) if row[1] is not None else None,
            'id_file': row[2],
        }
        for row in session.execute(obj_stmt).all()
    ]

    # --- objects_internal ---
    oi_stmt = (
        select(
            OI.id,
            OI.type,
            OI.dataset,
            OI.updated_transitive,
            OI.label,
            OI.curator_note,
        )
        .where(OI.dataset == F006_UUID)
        .order_by(OI.id)
    )
    data['objects_internal'] = [
        {
            'id': str(row[0]),
            'type': str(row[1]) if row[1] is not None else None,
            'dataset': str(row[2]) if row[2] is not None else None,
            'updated_transitive': str(row[3]) if row[3] is not None else None,
            'label': row[4],
            'curator_note': row[5],
        }
        for row in session.execute(oi_stmt).all()
    ]

    # --- dataset_object ---
    do_stmt = select(DO.dataset, DO.object).where(DO.dataset == F006_UUID).order_by(DO.object)
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
        .where(VI.dataset == F006_UUID)
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
        WHERE cv.dataset = :f006_uuid
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
        for row in session.execute(ip_stmt, {'f006_uuid': F006_UUID}).all()
    ]

    # --- equiv_inst ---
    ei_stmt = sql_text(
        """
        SELECT lv.id_formal AS left_formal,
               CAST(lv.dataset AS text) AS left_dataset,
               rv.id_formal AS right_formal,
               CAST(rv.dataset AS text) AS right_dataset
        FROM quantdb.equiv_inst ei
        JOIN quantdb.values_inst lv ON ei.left_thing = lv.id
        JOIN quantdb.values_inst rv ON ei.right_thing = rv.id
        WHERE lv.dataset = :f006_uuid
        ORDER BY lv.id_formal
    """
    )
    data['equiv_inst'] = [
        {
            'left_thing': {
                'dataset': row[1],
                'id_formal': row[0],
            },
            'right_thing': {
                'dataset': row[3],
                'id_formal': row[2],
            },
        }
        for row in session.execute(ei_stmt, {'f006_uuid': F006_UUID}).all()
    ]

    # --- values_quant (large: ~2.4M rows, use raw SQL) ---
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
            WHERE dataset = :f006_uuid
            UNION
            SELECT id FROM quantdb.objects_internal
            WHERE dataset = :f006_uuid
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
        for row in session.execute(vq_stmt, {'f006_uuid': F006_UUID}).all()
    ]

    # --- values_cat (large: ~609K rows, use raw SQL) ---
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
            WHERE dataset = :f006_uuid
            UNION
            SELECT id FROM quantdb.objects_internal
            WHERE dataset = :f006_uuid
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
        for row in session.execute(vc_stmt, {'f006_uuid': F006_UUID}).all()
    ]

    return data


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_f006_data(session, models):
    """Delete all f006 data in FK-safe child-first order.

    Deletion order (child-first to avoid IntegrityError):

    1. values_quant, values_cat
    2. obj_desc_quant, obj_desc_cat
    3. obj_desc_inst
    4. instance_parent, equiv_inst
    5. values_inst
    6. dataset_object
    7. objects_internal
    8. objects

    Parameters
    ----------
    session : Session
        SQLAlchemy session connected to quantdb_test.
    models : ReflectedModels
        Reflected ORM models from ``reflect_models()``.
    """
    # Collect all f006-related object UUIDs before deletion
    DO = models.DatasetObject
    OI = models.ObjectsInternal

    linked_uuids = {row[0] for row in session.execute(select(DO.object).where(DO.dataset == F006_UUID)).all()}
    internal_uuids = {row[0] for row in session.execute(select(OI.id).where(OI.dataset == F006_UUID)).all()}
    all_obj_uuids = list(linked_uuids | internal_uuids | {F006_UUID})

    # Build subquery for all f006 objects (package + internal)
    _obj_subquery = """
        (SELECT object FROM quantdb.dataset_object WHERE dataset = :uuid
         UNION
         SELECT id FROM quantdb.objects_internal WHERE dataset = :uuid)
    """

    # Disable triggers for faster bulk delete (only safe because we're
    # deleting in FK-safe order and the session user is superuser)
    _disable_triggers = [
        'ALTER TABLE quantdb.values_quant DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.values_cat DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.obj_desc_quant DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.obj_desc_cat DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.obj_desc_inst DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.instance_parent DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.equiv_inst DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.values_inst DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.dataset_object DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.objects_internal DISABLE TRIGGER ALL',
        'ALTER TABLE quantdb.objects DISABLE TRIGGER ALL',
    ]
    _enable_triggers = [s.replace('DISABLE', 'ENABLE') for s in _disable_triggers]

    for stmt in _disable_triggers:
        session.execute(sql_text(stmt))

    # Step 1: Delete values_quant and values_cat
    session.execute(
        sql_text('DELETE FROM quantdb.values_quant' f' WHERE object IN {_obj_subquery}'),
        {'uuid': F006_UUID},
    )
    session.execute(
        sql_text('DELETE FROM quantdb.values_cat' f' WHERE object IN {_obj_subquery}'),
        {'uuid': F006_UUID},
    )

    # Step 2: Delete obj_desc_quant, obj_desc_cat
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_quant' f' WHERE object IN {_obj_subquery}'),
        {'uuid': F006_UUID},
    )
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_cat' f' WHERE object IN {_obj_subquery}'),
        {'uuid': F006_UUID},
    )

    # Step 3: Delete obj_desc_inst
    session.execute(
        sql_text('DELETE FROM quantdb.obj_desc_inst' f' WHERE object IN {_obj_subquery}'),
        {'uuid': F006_UUID},
    )

    # Step 4: Delete instance_parent, equiv_inst
    _inst_subquery = '(SELECT id FROM quantdb.values_inst WHERE dataset = :uuid)'
    session.execute(
        sql_text('DELETE FROM quantdb.instance_parent' f' WHERE id IN {_inst_subquery}'),
        {'uuid': F006_UUID},
    )
    # equiv_inst has left_thing and right_thing both referencing
    # values_inst -- delete rows where either side is an f006 instance
    session.execute(
        sql_text('DELETE FROM quantdb.equiv_inst' f' WHERE left_thing IN {_inst_subquery}'),
        {'uuid': F006_UUID},
    )
    session.execute(
        sql_text('DELETE FROM quantdb.equiv_inst' f' WHERE right_thing IN {_inst_subquery}'),
        {'uuid': F006_UUID},
    )

    # Step 5: Delete values_inst
    session.execute(
        sql_text('DELETE FROM quantdb.values_inst WHERE dataset = :uuid'),
        {'uuid': F006_UUID},
    )

    # Step 6: Delete dataset_object
    session.execute(
        sql_text('DELETE FROM quantdb.dataset_object WHERE dataset = :uuid'),
        {'uuid': F006_UUID},
    )

    # Step 7: Delete the internal objects + their parent objects rows
    # Due to circular FK (objects.id_internal -> objects_internal),
    # we delete both at once: first the objects row (triggers are off
    # so FK check is skipped), then objects_internal
    # Delete the objects rows for internal objects first
    for oi_uuid in internal_uuids:
        session.execute(
            sql_text('DELETE FROM quantdb.objects WHERE id = :oid'),
            {'oid': oi_uuid},
        )

    # Step 8: Delete objects_internal
    session.execute(
        sql_text('DELETE FROM quantdb.objects_internal WHERE dataset = :uuid'),
        {'uuid': F006_UUID},
    )

    # Step 9: Delete remaining objects (package + dataset)
    remaining_uuids = [u for u in all_obj_uuids if u not in internal_uuids]
    if remaining_uuids:
        session.execute(
            sql_text('DELETE FROM quantdb.objects WHERE id = ANY(:uuids)'),
            {'uuids': remaining_uuids},
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
    """Build (dataset_uuid, id_formal) -> values_inst.id lookup for f006."""
    rows = session.execute(
        sql_text('SELECT id, CAST(dataset AS text), id_formal' ' FROM quantdb.values_inst' ' WHERE dataset = :uuid'),
        {'uuid': F006_UUID},
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


def ingest_f006_v2(session, models, data_dicts):
    """Insert f006 data in FK-safe parent-first order.

    Uses ``Ingest.batch()`` for small tables (objects, dataset_object,
    equiv_inst) to prove the deep upsert API works. Uses pre-resolved
    bulk SQL for large tables (values_inst 609K, instance_parent 609K,
    values_quant 2.4M, values_cat 609K) for practical performance.

    Insert ordering respects FK constraints and trigger prerequisites::

        objects -> objects_internal -> dataset_object -> values_inst ->
        instance_parent -> equiv_inst -> obj_desc_inst ->
        obj_desc_quant -> obj_desc_cat -> values_quant -> values_cat

    Parameters
    ----------
    session : Session
        SQLAlchemy session connected to quantdb_test.
    models : ReflectedModels
        Reflected ORM models from ``reflect_models()``.
    data_dicts : dict
        Output from ``extract_f006_from_db()``.
    """
    ing = Ingest(models)

    # Build FK lookup maps (label -> id) for bulk resolution
    di_map, dq_map, dc_map, ct_map = _build_fk_lookups(session, models)

    # ------------------------------------------------------------------
    # Step 1: Insert objects (small, ~123 rows, Ingest.batch())
    # ------------------------------------------------------------------
    regular_objects = []
    internal_objects = []
    for obj in data_dicts.get('objects', []):
        if obj.get('id_type') == 'quantdb':
            internal_objects.append(obj)
        else:
            regular_objects.append(obj)

    if regular_objects:
        ing.batch(session, 'objects', regular_objects)
    session.flush()

    # ------------------------------------------------------------------
    # Step 2: Handle objects_internal + internal objects (circular FK)
    # ------------------------------------------------------------------
    if internal_objects:
        session.execute(sql_text('ALTER TABLE quantdb.objects DISABLE TRIGGER ALL'))
        session.execute(
            sql_text('ALTER TABLE quantdb.objects' ' DROP CONSTRAINT' ' constraint_objects_remote_id_type_id_internal')
        )
        session.execute(sql_text('ALTER TABLE quantdb.objects' ' DROP CONSTRAINT IF EXISTS objects_id_internal_fkey'))

        for obj in internal_objects:
            session.execute(
                sql_text(
                    'INSERT INTO quantdb.objects'
                    ' (id, id_type, id_file)'
                    ' VALUES (:id, :id_type, :id_file)'
                    ' ON CONFLICT DO NOTHING'
                ),
                obj,
            )
        session.flush()

        for oi_dict in data_dicts.get('objects_internal', []):
            session.execute(
                sql_text(
                    'INSERT INTO quantdb.objects_internal'
                    ' (id, type, dataset, updated_transitive,'
                    ' label, curator_note)'
                    ' VALUES (:id, :type, :dataset,'
                    ' :updated_transitive, :label, :curator_note)'
                    ' ON CONFLICT DO NOTHING'
                ),
                oi_dict,
            )
        session.flush()

        for obj in internal_objects:
            session.execute(
                sql_text('UPDATE quantdb.objects' ' SET id_internal = :oid WHERE id = :oid'),
                {'oid': obj['id']},
            )

        session.execute(
            sql_text(
                'ALTER TABLE quantdb.objects'
                ' ADD CONSTRAINT objects_id_internal_fkey'
                ' FOREIGN KEY (id_internal)'
                ' REFERENCES quantdb.objects_internal(id)'
            )
        )
        session.execute(
            sql_text(
                'ALTER TABLE quantdb.objects ADD CONSTRAINT'
                ' constraint_objects_remote_id_type_id_internal'
                " CHECK (id_type <> 'quantdb'"
                ' OR (id_internal IS NOT NULL AND id = id_internal))'
            )
        )
        session.execute(sql_text('ALTER TABLE quantdb.objects ENABLE TRIGGER ALL'))
        session.flush()

    # ------------------------------------------------------------------
    # Step 3: Insert dataset_object (small, 121 rows, Ingest.batch())
    # ------------------------------------------------------------------
    if data_dicts.get('dataset_object'):
        ing.batch(session, 'dataset_object', data_dicts['dataset_object'])
        session.flush()

    # ------------------------------------------------------------------
    # Step 4: Insert values_inst (large, 609K rows, bulk insert)
    # ------------------------------------------------------------------
    vi_rows = data_dicts.get('values_inst', [])
    if vi_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_inst DISABLE TRIGGER ALL'))

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

        session.execute(sql_text('ALTER TABLE quantdb.values_inst ENABLE TRIGGER ALL'))
        session.flush()

    # Build instance lookup: (dataset_uuid, id_formal) -> int id
    inst_lookup = _build_instance_lookup(session)

    # ------------------------------------------------------------------
    # Step 5: Insert instance_parent (large, 609K rows, bulk insert)
    # ------------------------------------------------------------------
    ip_rows = data_dicts.get('instance_parent', [])
    if ip_rows:
        session.execute(sql_text('ALTER TABLE quantdb.instance_parent DISABLE TRIGGER ALL'))

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

        session.execute(sql_text('ALTER TABLE quantdb.instance_parent ENABLE TRIGGER ALL'))
        session.flush()

    # ------------------------------------------------------------------
    # Step 6: Insert equiv_inst (small, 37 rows, Ingest.batch())
    # ------------------------------------------------------------------
    if data_dicts.get('equiv_inst'):
        ing.batch(session, 'equiv_inst', data_dicts['equiv_inst'])
        session.flush()

    # ------------------------------------------------------------------
    # Step 7: Pre-create obj_desc_* prerequisite rows (bulk SQL)
    # ------------------------------------------------------------------
    odi_pairs, odq_pairs, odc_pairs = _collect_obj_desc_prerequisites(
        data_dicts,
        di_map,
        dq_map,
        dc_map,
    )

    if odi_pairs:
        odi_dicts = [{'object': obj, 'desc_inst': di, 'addr_field': _DEFAULT_ADDR_FIELD} for obj, di in odi_pairs]
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
        odq_dicts = [{'object': obj, 'desc_quant': dq, 'addr_field': _DEFAULT_ADDR_FIELD} for obj, dq in odq_pairs]
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
        odc_dicts = [{'object': obj, 'desc_cat': dc, 'addr_field': _DEFAULT_ADDR_FIELD} for obj, dc in odc_pairs]
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
    # Step 8: Insert values_quant (large, ~2.4M rows, bulk insert)
    # ------------------------------------------------------------------
    vq_rows = data_dicts.get('values_quant', [])
    if vq_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_quant DISABLE TRIGGER ALL'))

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

        session.execute(sql_text('ALTER TABLE quantdb.values_quant ENABLE TRIGGER ALL'))
        session.flush()

    # ------------------------------------------------------------------
    # Step 9: Insert values_cat (large, ~609K rows, bulk insert)
    # ------------------------------------------------------------------
    vc_rows = data_dicts.get('values_cat', [])
    if vc_rows:
        session.execute(sql_text('ALTER TABLE quantdb.values_cat DISABLE TRIGGER ALL'))

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

        session.execute(sql_text('ALTER TABLE quantdb.values_cat ENABLE TRIGGER ALL'))
        session.flush()
