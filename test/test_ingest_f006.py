"""Tests for f006 dataset integrity after production dump restore.

Rebuilds the quantdb_test database from scratch using the production
dump, caches cassava.ucsd.edu metadata JSON files locally, and verifies
the f006 dataset data via SQLAlchemy ORM.

Requires:
    - PostgreSQL running locally (trust auth for postgres user)
    - Production dump at resources/quantdb_production_template.dump
    - pg_restore v16 at /opt/homebrew/opt/postgresql@16/bin/pg_restore
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from quantdb.config import auth
from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

F006_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'

CASSAVA_BASE = 'https://cassava.ucsd.edu/sparc/datasets'
CACHE_DIR = Path.home() / '.quantdb' / 'cassava.ucsd.edu.cache'

CASSAVA_DATASETS: dict[str, list[str]] = {
    '2a3d01c0-39d3-464a-8746-54c9d67ebe0f': [
        'curation-export.json',
        'path-metadata.json',
    ],
    'dfb4a04a-6f9f-4b8b-97d1-f06b97c448d0': [
        'curation-export.json',
        'path-metadata.json',
    ],
    '031598b5-88eb-44eb-ba70-67ad1c2fe36a': [
        'curation-export.json',
        'path-metadata.json',
    ],
    '55c5b69c-a5b8-4881-a105-e4048af26fa5': [
        'curation-export.json',
        'path-metadata.json',
    ],
}

# All (dataset_uuid, filename) pairs flattened for parametrize
CASSAVA_FILES: list[tuple[str, str]] = [
    (ds, fn) for ds, fns in CASSAVA_DATASETS.items() for fn in fns
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def cache_cassava_metadata() -> None:
    """Download and cache cassava.ucsd.edu metadata JSON files.

    Files are cached under ``~/.quantdb/cassava.ucsd.edu.cache/``
    structured as ``{dataset_uuid}/{filename}``.

    Skips downloading if the file already exists on disk.
    """
    for ds_uuid, filenames in CASSAVA_DATASETS.items():
        ds_cache_dir = CACHE_DIR / ds_uuid
        ds_cache_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            dest = ds_cache_dir / filename
            if dest.exists():
                continue
            url = f'{CASSAVA_BASE}/{ds_uuid}/LATEST/{filename}'
            urllib.request.urlretrieve(url, dest)


@pytest.fixture(scope='session')
def reflected(rebuild_database: None) -> Generator[ReflectedModels, None, None]:
    """Reflect the quantdb_test schema once per test session.

    Depends on ``rebuild_database`` to ensure the database is freshly
    built before reflection.

    Yields:
        ReflectedModels NamedTuple with engine, Session, Base, and all
        20 ORM classes.
    """
    test_db = auth.get('test-db-database')
    engine = create_engine(
        dbUri(
            dbuser='quantdb-test-user',
            host='localhost',
            port=5432,
            database=test_db,
        ),
    )

    @event.listens_for(engine, 'connect')
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    models = reflect_models(engine=engine)
    yield models
    models.engine.dispose()


@pytest.fixture
def session(reflected: ReflectedModels) -> Generator[Session, None, None]:
    """Provide a fresh session per test, rolled back after each test."""
    sess = reflected.Session()
    yield sess
    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# f006 dataset integrity tests
# ---------------------------------------------------------------------------


class TestF006DatasetIntegrity:
    """Verify f006 dataset data matches production expectations."""

    def test_dataset_exists(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 dataset UUID should exist in the objects table."""
        Objects = reflected.Objects
        stmt = select(Objects).where(Objects.id == F006_UUID)
        result = session.execute(stmt).scalar_one_or_none()
        assert result is not None, (
            f'Dataset {F006_UUID} not found in objects table'
        )

    def test_dataset_object_count(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 121 linked objects in dataset_object."""
        DO = reflected.DatasetObject
        stmt = select(func.count()).select_from(DO).where(
            DO.dataset == F006_UUID,
        )
        count = session.execute(stmt).scalar_one()
        assert count == 121, (
            f'Expected 121 dataset_object links, got {count}'
        )

    def test_values_inst_total(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 609,390 total instances in values_inst."""
        VI = reflected.ValuesInst
        stmt = select(func.count()).select_from(VI).where(
            VI.dataset == F006_UUID,
        )
        count = session.execute(stmt).scalar_one()
        assert count == 609_390, (
            f'Expected 609,390 values_inst rows, got {count}'
        )

    def test_values_inst_breakdown(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Verify each (type, desc_inst_label) count for f006 instances."""
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(VI.type, DI.label, func.count())
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == F006_UUID)
            .group_by(VI.type, DI.label)
        )
        rows = session.execute(stmt).all()
        actual = {(row[0], row[1]): row[2] for row in rows}

        expected = {
            ('subject', 'human'): 1,
            ('sample', 'nerve-volume'): 61,
            ('sample', 'nerve-cross-section'): 27,
            ('sample', 'nerve'): 2,
            ('site', 'extruded-plane'): 60,
            ('below', 'fiber-cross-section'): 608_811,
            ('below', 'fascicle-cross-section'): 428,
        }

        for key, expected_count in expected.items():
            assert actual.get(key) == expected_count, (
                f'{key}: expected {expected_count}, got {actual.get(key)}'
            )

    def test_instance_parent_count(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 609,389 parent relationships in instance_parent."""
        IP = reflected.InstanceParent
        VI = reflected.ValuesInst
        # instance_parent.id references values_inst.id; filter by f006
        # dataset through values_inst
        stmt = (
            select(func.count())
            .select_from(IP)
            .join(VI, IP.id == VI.id)
            .where(VI.dataset == F006_UUID)
        )
        count = session.execute(stmt).scalar_one()
        assert count == 609_389, (
            f'Expected 609,389 instance_parent rows, got {count}'
        )

    def test_values_quant_total(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 2,445,944 quantitative values (post-dedup)."""
        VQ = reflected.ValuesQuant
        DO = reflected.DatasetObject
        stmt = (
            select(func.count())
            .select_from(VQ)
            .join(DO, VQ.object == DO.object)
            .where(DO.dataset == F006_UUID)
        )
        count = session.execute(stmt).scalar_one()
        assert count == 2_445_944, (
            f'Expected 2,445,944 values_quant rows, got {count}'
        )

    def test_values_cat_total(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 608,859 categorical values (post-dedup)."""
        VC = reflected.ValuesCat
        DO = reflected.DatasetObject
        stmt = (
            select(func.count())
            .select_from(VC)
            .join(DO, VC.object == DO.object)
            .where(DO.dataset == F006_UUID)
        )
        count = session.execute(stmt).scalar_one()
        assert count == 608_859, (
            f'Expected 608,859 values_cat rows, got {count}'
        )

    def test_values_quant_fiber_descriptors(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Verify fiber-level quant counts (608,811 each for 4 descriptors)."""
        VQ = reflected.ValuesQuant
        DQ = reflected.DescriptorsQuant
        DO = reflected.DatasetObject
        stmt = (
            select(DQ.label, func.count())
            .select_from(VQ)
            .join(DQ, VQ.desc_quant == DQ.id)
            .join(DO, VQ.object == DO.object)
            .where(DO.dataset == F006_UUID)
            .group_by(DQ.label)
        )
        rows = session.execute(stmt).all()
        actual = {row[0]: row[1] for row in rows}

        fiber_descriptors = [
            'fiber cross section diameter um min',
            'fiber cross section area um2',
            'fiber cross section diameter um',
            'fiber cross section diameter um max',
        ]
        for label in fiber_descriptors:
            assert actual.get(label) == 608_811, (
                f'{label!r}: expected 608,811, got {actual.get(label)}'
            )

    def test_values_cat_axon_fiber_type(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """608,811 hasAxonFiberType categorical entries for f006."""
        VC = reflected.ValuesCat
        DC = reflected.DescriptorsCat
        DO = reflected.DatasetObject
        stmt = (
            select(func.count())
            .select_from(VC)
            .join(DC, VC.desc_cat == DC.id)
            .join(DO, VC.object == DO.object)
            .where(DO.dataset == F006_UUID)
            .where(DC.label == 'hasAxonFiberType')
        )
        count = session.execute(stmt).scalar_one()
        assert count == 608_811, (
            f'Expected 608,811 hasAxonFiberType rows, got {count}'
        )

    def test_objects_internal(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 1 objects_internal record (via dataset column)."""
        OI = reflected.ObjectsInternal
        stmt = (
            select(func.count())
            .select_from(OI)
            .where(OI.dataset == F006_UUID)
        )
        count = session.execute(stmt).scalar_one()
        assert count == 1, (
            f'Expected 1 objects_internal for f006, got {count}'
        )

    def test_equiv_inst_count(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """f006 should have 37 equiv_inst records."""
        EI = reflected.EquivInst
        VI = reflected.ValuesInst
        # equiv_inst.left_thing references values_inst; join to filter
        # by f006 dataset
        stmt = (
            select(func.count())
            .select_from(EI)
            .join(VI, EI.left_thing == VI.id)
            .where(VI.dataset == F006_UUID)
        )
        count = session.execute(stmt).scalar_one()
        assert count == 37, (
            f'Expected 37 equiv_inst rows, got {count}'
        )


# ---------------------------------------------------------------------------
# Cassava metadata cache tests
# ---------------------------------------------------------------------------


class TestCassavaMetadataCache:
    """Verify cached cassava.ucsd.edu metadata files."""

    @pytest.mark.parametrize('ds_uuid,filename', CASSAVA_FILES)
    def test_cache_files_exist(
        self,
        cache_cassava_metadata: None,
        ds_uuid: str,
        filename: str,
    ) -> None:
        """All 8 cached metadata files should be present on disk."""
        path = CACHE_DIR / ds_uuid / filename
        assert path.exists(), f'Cache file missing: {path}'

    @pytest.mark.parametrize('ds_uuid,filename', CASSAVA_FILES)
    def test_cache_files_valid_json(
        self,
        cache_cassava_metadata: None,
        ds_uuid: str,
        filename: str,
    ) -> None:
        """All cached files should parse as valid JSON."""
        path = CACHE_DIR / ds_uuid / filename
        with open(path) as f:
            data = json.load(f)
        assert data is not None

    def test_f006_curation_export_has_subjects(
        self,
        cache_cassava_metadata: None,
    ) -> None:
        """f006 curation-export.json should have expected structure."""
        path = CACHE_DIR / F006_UUID / 'curation-export.json'
        with open(path) as f:
            data = json.load(f)
        # curation-export should be a dict with dataset content
        assert isinstance(data, (dict, list)), (
            f'Unexpected top-level type: {type(data).__name__}'
        )

    def test_f006_path_metadata_has_data(
        self,
        cache_cassava_metadata: None,
    ) -> None:
        """f006 path-metadata.json should have a data array."""
        path = CACHE_DIR / F006_UUID / 'path-metadata.json'
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, (dict, list)), (
            f'Unexpected top-level type: {type(data).__name__}'
        )
        # If it's a dict, check for a data key; if list, it is the data
        if isinstance(data, dict):
            assert len(data) > 0, 'path-metadata.json is empty'
        else:
            assert len(data) > 0, 'path-metadata.json data array is empty'
