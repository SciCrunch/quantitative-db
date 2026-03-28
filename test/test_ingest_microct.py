"""Tests for the MicroCT ingest pipeline (extract, delete, re-insert).

MicroCT data is NOT in the production dump, so the test builds
synthetic MicroCT data matching the schema (same descriptor labels,
same hierarchy structure) and tests the full ingest pipeline.

Requires:
    - PostgreSQL running on localhost:5432 (trust auth)
    - quantdb_test database restored from production dump
    - sql/inserts_microct.sql schema applied
"""
from __future__ import annotations

import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import text as sql_text

from quantdb.extract_microct import MICROCT_UUID
from quantdb.ingest_microct import (
    _count_microct,
    delete_microct_data,
    extract_microct_from_db,
    ingest_microct,
)
from quantdb.ingest_v2 import F006_UUID
from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri

# ---------------------------------------------------------------------------
# SQL paths
# ---------------------------------------------------------------------------

_SQL_DIR = Path(__file__).resolve().parent.parent / 'sql'


def _psql(sql=None, *, file=None, database='quantdb_test'):
    """Run psql against the local PostgreSQL instance."""
    cmd = [
        'psql', '-U', 'postgres',
        '-h', 'localhost', '-p', '5432',
        '-d', database,
        '-v', 'ON_ERROR_STOP=on',
    ]
    if file is not None:
        cmd.extend(['-f', str(file)])
    elif sql is not None:
        cmd.extend(['-c', sql])
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Synthetic MicroCT test data builder
# ---------------------------------------------------------------------------

# Use a stable fake UUID for test objects (not the dataset UUID)
_TEST_OBJ1 = 'aaaaaaaa-1111-2222-3333-444444444401'
_TEST_OBJ2 = 'aaaaaaaa-1111-2222-3333-444444444402'
_TEST_OBJ3 = 'aaaaaaaa-1111-2222-3333-444444444403'


def _build_synthetic_data():
    """Build synthetic MicroCT data_dicts for testing.

    Creates:
    - 1 dataset object + 3 package objects
    - 3 dataset_object links
    - 1 subject, 2 samples, 2 nerves, 4 slices, 6 fascicles = 15 values_inst
    - 14 instance_parent links (all non-root instances)
    - values_quant: 4 slices × 8 nerve descriptors + 6 fascicles × 7 descriptors = 74
    - values_cat: 6 fascicles × 3 edge descriptors = 18

    Hierarchy:
        sub-SR042 (subject, human)
          ├── sam-SR042-CL1 (sample, tissue)
          │   └── nerve-SR042-CL1-trunk (below, nerve)
          │       ├── nerve-SR042-CL1-trunk-slice-0 (below, nerve-cross-section)
          │       │   ├── nerve-SR042-CL1-trunk-frame-0-fasc-n1 (below, fascicle-cross-section)
          │       │   ├── nerve-SR042-CL1-trunk-frame-0-fasc-n2 (below, fascicle-cross-section)
          │       │   └── nerve-SR042-CL1-trunk-frame-0-fasc-n3 (below, fascicle-cross-section)
          │       └── nerve-SR042-CL1-trunk-slice-1 (below, nerve-cross-section)
          │           ├── nerve-SR042-CL1-trunk-frame-1-fasc-n4 (below, fascicle-cross-section)
          │           ├── nerve-SR042-CL1-trunk-frame-1-fasc-n5 (below, fascicle-cross-section)
          │           └── nerve-SR042-CL1-trunk-frame-1-fasc-n6 (below, fascicle-cross-section)
          └── sam-SR042-CL2 (sample, tissue)
              └── nerve-SR042-CL2-branch (below, nerve)
                  ├── nerve-SR042-CL2-branch-slice-0 (below, nerve-cross-section)
                  └── nerve-SR042-CL2-branch-slice-1 (below, nerve-cross-section)
    """
    objects = [
        {'id': MICROCT_UUID, 'id_type': 'dataset', 'id_file': None},
        {'id': _TEST_OBJ1, 'id_type': 'package', 'id_file': 100001},
        {'id': _TEST_OBJ2, 'id_type': 'package', 'id_file': 100002},
        {'id': _TEST_OBJ3, 'id_type': 'package', 'id_file': 100003},
    ]

    dataset_object = [
        {'dataset': MICROCT_UUID, 'object': _TEST_OBJ1},
        {'dataset': MICROCT_UUID, 'object': _TEST_OBJ2},
        {'dataset': MICROCT_UUID, 'object': _TEST_OBJ3},
    ]

    values_inst = [
        # Subject
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'sub-SR042',
            'type': 'subject',
            'desc_inst': 'human',
            'id_sub': 'sub-SR042',
        },
        # Samples
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'sam-SR042-CL1',
            'type': 'sample',
            'desc_inst': 'tissue',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'sam-SR042-CL2',
            'type': 'sample',
            'desc_inst': 'tissue',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL2',
        },
        # Nerves (id_sub is NOT NULL in the schema)
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk',
            'type': 'below',
            'desc_inst': 'nerve',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL2-branch',
            'type': 'below',
            'desc_inst': 'nerve',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL2',
        },
        # Slices (nerve cross-sections)
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-slice-0',
            'type': 'below',
            'desc_inst': 'nerve-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-slice-1',
            'type': 'below',
            'desc_inst': 'nerve-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL2-branch-slice-0',
            'type': 'below',
            'desc_inst': 'nerve-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL2',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL2-branch-slice-1',
            'type': 'below',
            'desc_inst': 'nerve-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL2',
        },
        # Fascicles
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-0-fasc-n1',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-0-fasc-n2',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-0-fasc-n3',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-1-fasc-n4',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-1-fasc-n5',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
        {
            'dataset': MICROCT_UUID,
            'id_formal': 'nerve-SR042-CL1-trunk-frame-1-fasc-n6',
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
            'id_sub': 'sub-SR042',
            'id_sam': 'sam-SR042-CL1',
        },
    ]

    instance_parent = [
        # Samples → subject
        _ip('sam-SR042-CL1', 'sub-SR042'),
        _ip('sam-SR042-CL2', 'sub-SR042'),
        # Nerves → samples
        _ip('nerve-SR042-CL1-trunk', 'sam-SR042-CL1'),
        _ip('nerve-SR042-CL2-branch', 'sam-SR042-CL2'),
        # Slices → nerves
        _ip('nerve-SR042-CL1-trunk-slice-0', 'nerve-SR042-CL1-trunk'),
        _ip('nerve-SR042-CL1-trunk-slice-1', 'nerve-SR042-CL1-trunk'),
        _ip('nerve-SR042-CL2-branch-slice-0', 'nerve-SR042-CL2-branch'),
        _ip('nerve-SR042-CL2-branch-slice-1', 'nerve-SR042-CL2-branch'),
        # Fascicles → slices
        _ip(
            'nerve-SR042-CL1-trunk-frame-0-fasc-n1',
            'nerve-SR042-CL1-trunk-slice-0',
        ),
        _ip(
            'nerve-SR042-CL1-trunk-frame-0-fasc-n2',
            'nerve-SR042-CL1-trunk-slice-0',
        ),
        _ip(
            'nerve-SR042-CL1-trunk-frame-0-fasc-n3',
            'nerve-SR042-CL1-trunk-slice-0',
        ),
        _ip(
            'nerve-SR042-CL1-trunk-frame-1-fasc-n4',
            'nerve-SR042-CL1-trunk-slice-1',
        ),
        _ip(
            'nerve-SR042-CL1-trunk-frame-1-fasc-n5',
            'nerve-SR042-CL1-trunk-slice-1',
        ),
        _ip(
            'nerve-SR042-CL1-trunk-frame-1-fasc-n6',
            'nerve-SR042-CL1-trunk-slice-1',
        ),
    ]

    # Build values_quant: nerve measurements + fascicle measurements
    nerve_descs = [
        'nerve cross section area um2',
        'nerve cross section perimeter um',
        'nerve cross section diameter um',
        'nerve cross section centroid-x um',
        'nerve cross section centroid-y um',
        'nerve cross section major axis um',
        'nerve cross section minor axis um',
        'nerve cross section angle degree',
    ]
    fascicle_descs = [
        'fascicle cross section area um2',
        'fascicle cross section diameter um',
        'fascicle cross section centroid-0 um',
        'fascicle cross section centroid-1 um',
        'fascicle cross section ellipse major axis um',
        'fascicle cross section ellipse minor axis um',
        'fascicle cross section ellipse angle degree',
    ]

    values_quant = []
    val_counter = 1.0

    # Nerve slice measurements (4 slices × 8 descs = 32)
    for slice_id in [
        'nerve-SR042-CL1-trunk-slice-0',
        'nerve-SR042-CL1-trunk-slice-1',
        'nerve-SR042-CL2-branch-slice-0',
        'nerve-SR042-CL2-branch-slice-1',
    ]:
        obj = _TEST_OBJ1 if 'CL1' in slice_id else _TEST_OBJ2
        for desc in nerve_descs:
            values_quant.append({
                'value': val_counter,
                'value_blob': val_counter,
                'object': obj,
                'desc_inst': 'nerve-cross-section',
                'desc_quant': desc,
                'instance': {
                    'dataset': MICROCT_UUID,
                    'id_formal': slice_id,
                },
            })
            val_counter += 1.0

    # Fascicle measurements (6 fascicles × 7 descs = 42)
    for fasc_id in [
        'nerve-SR042-CL1-trunk-frame-0-fasc-n1',
        'nerve-SR042-CL1-trunk-frame-0-fasc-n2',
        'nerve-SR042-CL1-trunk-frame-0-fasc-n3',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n4',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n5',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n6',
    ]:
        for desc in fascicle_descs:
            values_quant.append({
                'value': val_counter,
                'value_blob': val_counter,
                'object': _TEST_OBJ3,
                'desc_inst': 'fascicle-cross-section',
                'desc_quant': desc,
                'instance': {
                    'dataset': MICROCT_UUID,
                    'id_formal': fasc_id,
                },
            })
            val_counter += 1.0

    # Build values_cat: edge properties for fascicles
    edge_descs = [
        'fascicleEdgeIdentity',
        'fascicleEdgeSplit',
        'fascicleEdgeMerge',
    ]
    values_cat = []
    for fasc_id in [
        'nerve-SR042-CL1-trunk-frame-0-fasc-n1',
        'nerve-SR042-CL1-trunk-frame-0-fasc-n2',
        'nerve-SR042-CL1-trunk-frame-0-fasc-n3',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n4',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n5',
        'nerve-SR042-CL1-trunk-frame-1-fasc-n6',
    ]:
        for desc in edge_descs:
            values_cat.append({
                'value_controlled': 'true',
                'value_open': None,
                'object': _TEST_OBJ3,
                'desc_inst': 'fascicle-cross-section',
                'desc_cat': desc,
                'instance': {
                    'dataset': MICROCT_UUID,
                    'id_formal': fasc_id,
                },
            })

    return {
        'objects': objects,
        'dataset_object': dataset_object,
        'values_inst': values_inst,
        'instance_parent': instance_parent,
        'values_quant': values_quant,
        'values_cat': values_cat,
    }


def _ip(child, parent):
    """Helper to build instance_parent dict in ingest format."""
    return {
        'id': {'dataset': MICROCT_UUID, 'id_formal': child},
        'parent': {'dataset': MICROCT_UUID, 'id_formal': parent},
    }


# ---------------------------------------------------------------------------
# Expected counts from synthetic data
# ---------------------------------------------------------------------------

EXPECTED_COUNTS = {
    'objects': 4,         # 1 dataset + 3 package
    'dataset_object': 3,
    'values_inst': 15,    # 1 subject + 2 samples + 2 nerves + 4 slices + 6 fascicles
    'instance_parent': 14,
    'values_quant': 74,   # 32 nerve + 42 fascicle
    'values_cat': 18,     # 6 fascicles × 3 edge descriptors
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def reflected(rebuild_database) -> Generator[ReflectedModels, None, None]:
    """Reflect quantdb_test schema once per module."""
    try:
        engine = create_engine(
            dbUri(
                dbuser='postgres',
                host='localhost',
                port=5432,
                database='quantdb_test',
            ),
        )

        @event.listens_for(engine, 'connect')
        def _set_search_path(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('SET search_path TO quantdb, public')
            cursor.close()

        models = reflect_models(engine=engine)
    except Exception as e:
        pytest.skip(f'quantdb_test database not available: {e}')
    yield models
    models.engine.dispose()


@pytest.fixture(scope='module')
def schema_applied(reflected):
    """Ensure MicroCT schema inserts are applied."""
    _psql(file=_SQL_DIR / 'inserts_microct.sql')
    return True


# Module-level containers
_first_ingest_counts: dict = {}
_baseline_quant_samples: list = []
_baseline_cat_samples: list = []


@pytest.fixture(scope='module')
def microct_ingested(
    reflected: ReflectedModels,
    schema_applied,
) -> Generator[Session, None, None]:
    """Ingest synthetic MicroCT data, then run DB round-trip.

    1. Ingest synthetic data from cassava-style flat dicts
    2. Record post-ingest counts and baseline samples
    3. Extract from DB → delete → verify zeros → re-ingest
    4. Yield session for test assertions
    """
    sess = reflected.Session()

    try:
        # Verify no MicroCT data exists yet
        pre_counts = _count_microct(sess, reflected)
        assert pre_counts['values_inst'] == 0, (
            'MicroCT data already exists in DB'
        )

        # ---- Phase 1: Ingest synthetic data ----
        data_dicts = _build_synthetic_data()
        ingest_microct(sess, reflected, data_dicts)
        sess.commit()

        # Record first-ingest counts
        _first_ingest_counts.update(_count_microct(sess, reflected))

        # Capture baseline samples
        _baseline_quant_samples.clear()
        _baseline_quant_samples.extend(_sample_values_quant(sess))
        _baseline_cat_samples.clear()
        _baseline_cat_samples.extend(_sample_values_cat(sess))

        # ---- Phase 2: DB round-trip ----
        db_data = extract_microct_from_db(sess, reflected)
        delete_microct_data(sess, reflected)
        sess.commit()

        # Verify zeros
        zero_counts = _count_microct(sess, reflected)
        for table_name, count in zero_counts.items():
            assert count == 0, (
                f'{table_name}: expected 0 after deletion, got {count}'
            )

        # Re-ingest from DB-extracted data
        ingest_microct(sess, reflected, db_data)
        sess.commit()

        yield sess

    finally:
        sess.rollback()
        sess.close()


# ---------------------------------------------------------------------------
# Helpers: count f006 data
# ---------------------------------------------------------------------------


def _count_f006(session, models):
    """Return a dict of f006 row counts for key tables."""
    counts = {}
    VI = models.ValuesInst
    counts['values_inst'] = session.execute(
        select(func.count()).select_from(VI).where(
            VI.dataset == F006_UUID
        )
    ).scalar_one()

    DO = models.DatasetObject
    counts['dataset_object'] = session.execute(
        select(func.count()).select_from(DO).where(
            DO.dataset == F006_UUID
        )
    ).scalar_one()

    VQ = models.ValuesQuant
    counts['values_quant'] = session.execute(
        select(func.count())
        .select_from(VQ)
        .join(DO, VQ.object == DO.object)
        .where(DO.dataset == F006_UUID)
    ).scalar_one()

    VC = models.ValuesCat
    counts['values_cat'] = session.execute(
        select(func.count())
        .select_from(VC)
        .join(DO, VC.object == DO.object)
        .where(DO.dataset == F006_UUID)
    ).scalar_one()

    return counts


# ---------------------------------------------------------------------------
# Helpers: sampling
# ---------------------------------------------------------------------------


def _sample_values_quant(session, limit=100):
    """Capture a deterministic sample of values_quant rows."""
    stmt = sql_text("""
        SELECT CAST(vq.value AS text) AS value_str,
               CAST(vq.value_blob AS text) AS value_blob_str,
               vi.id_formal AS instance_id_formal,
               dq.label AS desc_quant_label,
               CAST(vq.object AS text) AS object_uuid
        FROM quantdb.values_quant vq
        JOIN quantdb.values_inst vi ON vq.instance = vi.id
        JOIN quantdb.descriptors_quant dq ON vq.desc_quant = dq.id
        WHERE vq.object IN (
            SELECT object FROM quantdb.dataset_object
            WHERE dataset = :uuid
        )
        ORDER BY vi.id_formal, dq.label, CAST(vq.object AS text)
        LIMIT :lim
    """)
    rows = session.execute(
        stmt, {'uuid': MICROCT_UUID, 'lim': limit}
    ).all()
    return [
        {
            'value': r[0],
            'value_blob': r[1],
            'instance_id_formal': r[2],
            'desc_quant_label': r[3],
            'object_uuid': r[4],
        }
        for r in rows
    ]


def _sample_values_cat(session, limit=100):
    """Capture a deterministic sample of values_cat rows."""
    stmt = sql_text("""
        SELECT vc.value_open,
               ct.label AS value_controlled_label,
               vi.id_formal AS instance_id_formal,
               dc.label AS desc_cat_label,
               CAST(vc.object AS text) AS object_uuid
        FROM quantdb.values_cat vc
        JOIN quantdb.values_inst vi ON vc.instance = vi.id
        JOIN quantdb.descriptors_cat dc ON vc.desc_cat = dc.id
        LEFT JOIN quantdb.controlled_terms ct
            ON vc.value_controlled = ct.id
        WHERE vc.object IN (
            SELECT object FROM quantdb.dataset_object
            WHERE dataset = :uuid
        )
        ORDER BY vi.id_formal, dc.label, CAST(vc.object AS text)
        LIMIT :lim
    """)
    rows = session.execute(
        stmt, {'uuid': MICROCT_UUID, 'lim': limit}
    ).all()
    return [
        {
            'value_open': r[0],
            'value_controlled_label': r[1],
            'instance_id_formal': r[2],
            'desc_cat_label': r[3],
            'object_uuid': r[4],
        }
        for r in rows
    ]


def _normalize_numeric_str(s):
    """Normalize a numeric string so '2' and '2.0' compare equal."""
    if s is None:
        return None
    try:
        return str(Decimal(s).normalize())
    except InvalidOperation:
        return s


# ===================================================================
# Tests: Ingest counts (VAL-INGEST-001)
# ===================================================================


class TestIngestCounts:
    """Verify all table counts after ingest."""

    def test_values_inst_count(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['values_inst'] == EXPECTED_COUNTS['values_inst']

    def test_dataset_object_count(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['dataset_object'] == EXPECTED_COUNTS['dataset_object']

    def test_instance_parent_count(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['instance_parent'] == EXPECTED_COUNTS['instance_parent']

    def test_values_quant_count(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['values_quant'] == EXPECTED_COUNTS['values_quant']

    def test_values_cat_count(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['values_cat'] == EXPECTED_COUNTS['values_cat']

    def test_all_counts_nonzero(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        for table, count in counts.items():
            assert count > 0, f'{table} should be > 0 after ingest'


# ===================================================================
# Tests: Values_inst breakdown (VAL-INGEST-002)
# ===================================================================


class TestValuesInstBreakdown:
    """Verify (type, desc_inst) grouped counts."""

    def test_values_inst_breakdown(self, microct_ingested, reflected):
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(VI.type, DI.label, func.count())
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == MICROCT_UUID)
            .group_by(VI.type, DI.label)
            .order_by(VI.type, DI.label)
        )
        rows = microct_ingested.execute(stmt).all()
        breakdown = {(row[0], row[1]): row[2] for row in rows}

        assert breakdown[('subject', 'human')] == 1
        assert breakdown[('sample', 'tissue')] == 2
        assert breakdown[('below', 'nerve')] == 2
        assert breakdown[('below', 'nerve-cross-section')] == 4
        assert breakdown[('below', 'fascicle-cross-section')] == 6


# ===================================================================
# Tests: obj_desc prerequisites (VAL-INGEST-003)
# ===================================================================


class TestObjDescPrerequisites:
    """Verify obj_desc_inst/quant/cat counts."""

    def test_obj_desc_inst_exists(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['obj_desc_inst'] > 0

    def test_obj_desc_quant_exists(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['obj_desc_quant'] > 0

    def test_obj_desc_cat_exists(self, microct_ingested, reflected):
        counts = _count_microct(microct_ingested, reflected)
        assert counts['obj_desc_cat'] > 0


# ===================================================================
# Tests: Instance hierarchy (VAL-INTEGRITY-001)
# ===================================================================


class TestInstanceHierarchy:
    """Verify every non-root has parent, no orphans."""

    def test_every_nonroot_has_parent(self, microct_ingested, reflected):
        orphan_stmt = sql_text("""
            SELECT COUNT(*)
            FROM quantdb.values_inst vi
            WHERE vi.dataset = :uuid
            AND vi.type != 'subject'
            AND vi.id NOT IN (
                SELECT ip.id FROM quantdb.instance_parent ip
                JOIN quantdb.values_inst v2 ON ip.id = v2.id
                WHERE v2.dataset = :uuid
            )
        """)
        orphan_count = microct_ingested.execute(
            orphan_stmt, {'uuid': MICROCT_UUID}
        ).scalar_one()
        assert orphan_count == 0, (
            f'{orphan_count} non-subject instances without parent'
        )

    def test_no_dangling_parent_refs(self, microct_ingested, reflected):
        dangling_stmt = sql_text("""
            SELECT COUNT(*)
            FROM quantdb.instance_parent ip
            JOIN quantdb.values_inst cv ON ip.id = cv.id
            WHERE cv.dataset = :uuid
            AND ip.parent NOT IN (
                SELECT id FROM quantdb.values_inst
            )
        """)
        dangling_count = microct_ingested.execute(
            dangling_stmt, {'uuid': MICROCT_UUID}
        ).scalar_one()
        assert dangling_count == 0, (
            f'{dangling_count} dangling parent references'
        )


# ===================================================================
# Tests: Values reference valid instances (VAL-INTEGRITY-002)
# ===================================================================


class TestValuesReferenceValidInstances:
    """Verify no orphaned values."""

    def test_values_quant_no_orphans(self, microct_ingested, reflected):
        orphan_stmt = sql_text("""
            SELECT COUNT(*)
            FROM quantdb.values_quant vq
            WHERE vq.object IN (
                SELECT object FROM quantdb.dataset_object
                WHERE dataset = :uuid
            )
            AND vq.instance NOT IN (
                SELECT id FROM quantdb.values_inst
            )
        """)
        count = microct_ingested.execute(
            orphan_stmt, {'uuid': MICROCT_UUID}
        ).scalar_one()
        assert count == 0, f'{count} orphaned values_quant rows'

    def test_values_cat_no_orphans(self, microct_ingested, reflected):
        orphan_stmt = sql_text("""
            SELECT COUNT(*)
            FROM quantdb.values_cat vc
            WHERE vc.object IN (
                SELECT object FROM quantdb.dataset_object
                WHERE dataset = :uuid
            )
            AND vc.instance NOT IN (
                SELECT id FROM quantdb.values_inst
            )
        """)
        count = microct_ingested.execute(
            orphan_stmt, {'uuid': MICROCT_UUID}
        ).scalar_one()
        assert count == 0, f'{count} orphaned values_cat rows'


# ===================================================================
# Tests: Spot-check values (VAL-INTEGRITY-003)
# ===================================================================


class TestSpotCheckValues:
    """Sample values_quant rows, compare field-by-field."""

    def test_spot_check_values_quant(self, microct_ingested, reflected):
        baseline = _baseline_quant_samples
        assert len(baseline) > 0, 'No baseline quant samples captured'

        post = _sample_values_quant(microct_ingested)
        assert len(post) == len(baseline), (
            f'Expected {len(baseline)} rows, got {len(post)}'
        )

        for i, (bl, pi) in enumerate(zip(baseline, post)):
            assert bl['instance_id_formal'] == pi['instance_id_formal'], (
                f'Row {i}: instance mismatch'
            )
            assert bl['desc_quant_label'] == pi['desc_quant_label'], (
                f'Row {i}: desc_quant mismatch'
            )
            assert bl['object_uuid'] == pi['object_uuid'], (
                f'Row {i}: object mismatch'
            )
            assert _normalize_numeric_str(bl['value']) == \
                _normalize_numeric_str(pi['value']), (
                    f'Row {i}: value mismatch: '
                    f'{bl["value"]!r} != {pi["value"]!r}'
                )
            assert _normalize_numeric_str(bl['value_blob']) == \
                _normalize_numeric_str(pi['value_blob']), (
                    f'Row {i}: value_blob mismatch'
                )

    def test_spot_check_values_cat(self, microct_ingested, reflected):
        baseline = _baseline_cat_samples
        if len(baseline) == 0:
            pytest.skip('No baseline cat samples')

        post = _sample_values_cat(microct_ingested)
        assert len(post) == len(baseline)

        for i, (bl, pi) in enumerate(zip(baseline, post)):
            assert bl['instance_id_formal'] == pi['instance_id_formal']
            assert bl['desc_cat_label'] == pi['desc_cat_label']
            assert bl['object_uuid'] == pi['object_uuid']
            assert bl['value_controlled_label'] == \
                pi['value_controlled_label']


# ===================================================================
# Tests: Delete zeros (VAL-DELETE-001)
# ===================================================================


class TestDeleteZeros:
    """Verify deletion produces zero counts.

    Uses the microct_ingested fixture which has data already loaded.
    Performs delete → verify zeros → re-ingest to restore state.
    """

    def test_delete_zeros(self, microct_ingested, reflected):
        # Data exists from the fixture
        pre = _count_microct(microct_ingested, reflected)
        assert pre['values_inst'] > 0, 'Data must exist before delete test'

        # Extract before deleting (to restore later)
        backup = extract_microct_from_db(microct_ingested, reflected)

        # Delete
        delete_microct_data(microct_ingested, reflected)

        # Verify zero
        post = _count_microct(microct_ingested, reflected)
        for table, count in post.items():
            assert count == 0, f'{table}: expected 0, got {count}'

        # Restore data for subsequent tests
        ingest_microct(microct_ingested, reflected, backup)


# ===================================================================
# Tests: Delete preserves other data (VAL-DELETE-002)
# ===================================================================


class TestDeletePreservesOtherData:
    """Verify f006 data unaffected by MicroCT deletion."""

    def test_f006_unaffected(self, microct_ingested, reflected):
        f006 = _count_f006(microct_ingested, reflected)
        assert f006['values_inst'] == 609_390
        assert f006['dataset_object'] == 121


# ===================================================================
# Tests: Roundtrip counts (VAL-ROUNDTRIP-001)
# ===================================================================


class TestRoundtripCounts:
    """Extract → delete → re-ingest → compare counts."""

    def test_roundtrip_counts_match(self, microct_ingested, reflected):
        post = _count_microct(microct_ingested, reflected)
        for table_name in _first_ingest_counts:
            assert _first_ingest_counts[table_name] == post[table_name], (
                f'{table_name}: first={_first_ingest_counts[table_name]}, '
                f'roundtrip={post[table_name]}'
            )


# ===================================================================
# Tests: Roundtrip spot-check (VAL-ROUNDTRIP-002)
# ===================================================================


class TestRoundtripSpotCheck:
    """Spot-check values after round-trip."""

    def test_roundtrip_spot_check_quant(
        self, microct_ingested, reflected
    ):
        baseline = _baseline_quant_samples
        assert len(baseline) > 0
        post = _sample_values_quant(microct_ingested)
        assert len(post) == len(baseline)

        mismatches = 0
        for bl, pi in zip(baseline, post):
            if _normalize_numeric_str(bl['value']) != \
               _normalize_numeric_str(pi['value']):
                mismatches += 1
        assert mismatches == 0, f'{mismatches} value mismatches'


# ===================================================================
# Tests: Idempotent (VAL-ROUNDTRIP-003)
# ===================================================================


class TestIdempotent:
    """Second round-trip produces same counts."""

    def test_idempotent(self, microct_ingested, reflected):
        first_counts = _count_microct(microct_ingested, reflected)

        # Second cycle
        data2 = extract_microct_from_db(microct_ingested, reflected)
        delete_microct_data(microct_ingested, reflected)

        zero = _count_microct(microct_ingested, reflected)
        for table_name, count in zero.items():
            assert count == 0, (
                f'{table_name}: expected 0 after 2nd delete, got {count}'
            )

        ingest_microct(microct_ingested, reflected, data2)

        second_counts = _count_microct(microct_ingested, reflected)
        for table_name in first_counts:
            assert first_counts[table_name] == second_counts[table_name], (
                f'{table_name}: first={first_counts[table_name]}, '
                f'second={second_counts[table_name]}'
            )


# ===================================================================
# Tests: Full pipeline (VAL-CROSS-002)
# ===================================================================


class TestFullPipeline:
    """End-to-end: schema SQL → extract → ingest → verify → delete → reingest."""

    def test_full_pipeline(self, microct_ingested, reflected):
        """The microct_ingested fixture already runs the full pipeline.

        1. Schema SQL applied (schema_applied fixture)
        2. Synthetic extraction + ingestion
        3. Verify counts (non-zero)
        4. Extract from DB → Delete (verify zeros) → Re-ingest
        5. Verify counts match first ingest

        This test confirms the end-to-end result.
        """
        counts = _count_microct(microct_ingested, reflected)
        assert counts['values_inst'] == EXPECTED_COUNTS['values_inst']
        assert counts['dataset_object'] == EXPECTED_COUNTS['dataset_object']
        assert counts['values_quant'] == EXPECTED_COUNTS['values_quant']
        assert counts['values_cat'] == EXPECTED_COUNTS['values_cat']
        assert counts['instance_parent'] == EXPECTED_COUNTS['instance_parent']

        # Verify counts match first ingest
        for table_name in _first_ingest_counts:
            assert _first_ingest_counts[table_name] == counts[table_name]
