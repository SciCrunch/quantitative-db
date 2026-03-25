"""Tests for f006 snapshot extraction and fixture integrity.

Verifies that:
  - Fixture files exist for all expected tables
  - Summary counts match production expectations
  - Full-row fixtures have correct row counts
  - Extraction is deterministic (two runs produce identical files)
  - Comparison utility detects differences

Requires:
    - PostgreSQL running locally (trust auth for postgres user)
    - Production dump restored via rebuild_database fixture
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from quantdb.config import auth  # noqa: F401 (used in ensure_database)
from quantdb.models import ReflectedModels, reflect_models
from quantdb.snapshot import F006_UUID, compare_snapshot, extract_f006_snapshot
from quantdb.utils import dbUri


# ---------------------------------------------------------------------------
# ensure_database fixture (idempotent; skips rebuild if data present)
# ---------------------------------------------------------------------------

_SQL_DIR = Path(__file__).resolve().parent.parent / 'sql'
_PROD_DUMP = Path(__file__).resolve().parent.parent / 'resources' / 'quantdb_production_template.dump'
_PG_RESTORE = '/opt/homebrew/opt/postgresql@16/bin/pg_restore'


def _psql(sql=None, *, file=None, database='postgres', host='localhost',
           port=5432, extra_vars=None):
    cmd = [
        'psql', '-U', 'postgres',
        '-h', host, '-p', str(port),
        '-d', database,
        '-v', 'ON_ERROR_STOP=on',
    ]
    if extra_vars:
        for k, v in extra_vars.items():
            cmd.extend(['-v', f'{k}={v}'])
    if file is not None:
        cmd.extend(['-f', str(file)])
    elif sql is not None:
        cmd.extend(['-c', sql])
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _database_has_f006_data():
    """Check if quantdb_test already has f006 production data."""
    try:
        result = subprocess.run(
            ['psql', '-U', 'postgres', '-h', 'localhost', '-p', '5432',
             '-d', 'quantdb_test', '-t', '-A', '-c',
             "SELECT count(*) FROM quantdb.values_inst"
             " WHERE dataset = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return count == 609_390
    except (ValueError, subprocess.SubprocessError):
        pass
    return False


@pytest.fixture(scope='session')
def ensure_database():
    """Ensure quantdb_test has production f006 data; rebuild only if needed.

    When the full test suite runs, test_ingest_f006.py's rebuild_database
    fixture will have already rebuilt the database.  This fixture checks
    first and skips the rebuild in that case, avoiding conflicts.
    """
    if _database_has_f006_data():
        return

    test_db = auth.get('test-db-database')
    assert test_db == 'quantdb_test'

    _psql(file=_SQL_DIR / 'postgres.sql', extra_vars={
        'test_database': test_db, 'database': test_db,
    })
    _psql(sql='GRANT "quantdb-test-admin" TO CURRENT_USER;')
    _psql(sql=f'DROP DATABASE IF EXISTS {test_db};')
    _psql(sql=(
        f'CREATE DATABASE {test_db}'
        f"  WITH OWNER = 'quantdb-test-admin'"
        f"  TEMPLATE template0"
        f"  ENCODING = 'UTF8'"
        f"  LC_COLLATE = 'C'"
        f"  LC_CTYPE = 'C'"
        f"  CONNECTION LIMIT = -1;"
    ))
    _psql(sql='REVOKE "quantdb-test-admin" FROM CURRENT_USER;')
    _psql(sql='ALTER ROLE postgres SET search_path = quantdb, public;')
    _psql(file=_SQL_DIR / 'schemas.sql', database=test_db)
    _psql(file=_SQL_DIR / 'tables.sql', database=test_db)
    _psql(
        file=_SQL_DIR / 'permissions.sql', database=test_db,
        extra_vars={'database': test_db, 'perm_user': 'quantdb-test-user'},
    )
    _psql(sql=(
        'ALTER TABLE quantdb.values_cat'
        '  DROP CONSTRAINT IF EXISTS'
        '  values_cat_object_instance_desc_cat_key;'
        ' ALTER TABLE quantdb.values_quant'
        '  DROP CONSTRAINT IF EXISTS'
        '  values_quant_object_instance_desc_quant_key;'
    ), database=test_db)
    subprocess.run([
        _PG_RESTORE,
        '--data-only', '--schema=quantdb',
        '--no-owner', '--no-privileges', '--disable-triggers',
        '-U', 'postgres', '-h', 'localhost', '-p', '5432',
        '-d', test_db, str(_PROD_DUMP),
    ], check=True, capture_output=True, text=True)
    _psql(sql=(
        'DELETE FROM quantdb.values_cat a USING quantdb.values_cat b'
        '  WHERE a.id > b.id AND a.object = b.object'
        '  AND a.instance = b.instance AND a.desc_cat = b.desc_cat;'
        ' DELETE FROM quantdb.values_quant a USING quantdb.values_quant b'
        '  WHERE a.id > b.id AND a.object = b.object'
        '  AND a.instance = b.instance AND a.desc_quant = b.desc_quant;'
        ' ALTER TABLE quantdb.values_cat'
        '  ADD CONSTRAINT values_cat_object_instance_desc_cat_key'
        '  UNIQUE (object, instance, desc_cat);'
        ' ALTER TABLE quantdb.values_quant'
        '  ADD CONSTRAINT values_quant_object_instance_desc_quant_key'
        '  UNIQUE (object, instance, desc_quant);'
    ), database=test_db)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / 'test' / 'fixtures' / 'f006'

EXPECTED_FILES = [
    'values_inst_summary.json',
    'values_quant_summary.json',
    'values_cat_summary.json',
    'instance_parent_count.json',
    'dataset_object.json',
    'equiv_inst.json',
    'objects_internal.json',
    'objects.json',
    'obj_desc_inst.json',
    'obj_desc_quant.json',
    'obj_desc_cat.json',
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def reflected(ensure_database: None) -> Generator[ReflectedModels, None, None]:
    """Reflect the quantdb_test schema once per test session."""
    engine = create_engine(
        dbUri(
            dbuser='quantdb-test-user',
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
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name):
    """Load a fixture JSON file from the f006 fixtures directory."""
    path = FIXTURES_DIR / name
    with open(path) as f:
        return json.load(f)


def _sha256(path):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Test: Fixture files exist
# ---------------------------------------------------------------------------


class TestFixtureFilesExist:
    """VAL-SNAP-001: Fixture files created for all f006 tables."""

    @pytest.mark.parametrize('filename', EXPECTED_FILES)
    def test_fixture_file_exists(self, filename: str) -> None:
        """Each expected fixture file should exist on disk."""
        path = FIXTURES_DIR / filename
        assert path.exists(), f'Fixture file missing: {path}'

    def test_fixture_count(self) -> None:
        """Should have at least 11 fixture files."""
        json_files = list(FIXTURES_DIR.glob('*.json'))
        assert len(json_files) >= 11, (
            f'Expected >= 11 fixture files, found {len(json_files)}'
        )


# ---------------------------------------------------------------------------
# Test: Summary counts match production
# ---------------------------------------------------------------------------


class TestValuesInstSummary:
    """VAL-SNAP-002: values_inst count and breakdown matches production."""

    def test_total_count(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['total'] == 609_390

    def test_breakdown_subject_human(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['subject|human'] == 1

    def test_breakdown_sample_nerve_volume(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['sample|nerve-volume'] == 61

    def test_breakdown_sample_nerve_cross_section(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['sample|nerve-cross-section'] == 27

    def test_breakdown_sample_nerve(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['sample|nerve'] == 2

    def test_breakdown_site_extruded_plane(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['site|extruded-plane'] == 60

    def test_breakdown_below_fiber_cross_section(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['below|fiber-cross-section'] == 608_811

    def test_breakdown_below_fascicle_cross_section(self) -> None:
        data = _load_fixture('values_inst_summary.json')
        assert data['breakdown']['below|fascicle-cross-section'] == 428

    def test_breakdown_vs_db(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Fixture breakdown matches live DB query result."""
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(VI.type, DI.label, func.count())
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == F006_UUID)
            .group_by(VI.type, DI.label)
        )
        rows = session.execute(stmt).all()
        db_breakdown = {f"{r[0]}|{r[1]}": r[2] for r in rows}

        fixture = _load_fixture('values_inst_summary.json')
        assert fixture['breakdown'] == db_breakdown


class TestDatasetObjectFixture:
    """VAL-SNAP-003: dataset_object fixture matches production (121 rows)."""

    def test_row_count(self) -> None:
        data = _load_fixture('dataset_object.json')
        assert len(data) == 121

    def test_all_rows_have_f006_dataset(self) -> None:
        data = _load_fixture('dataset_object.json')
        for row in data:
            assert row['dataset'] == F006_UUID

    def test_matches_db(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Fixture rows match live DB exactly."""
        DO = reflected.DatasetObject
        stmt = (
            select(DO.dataset, DO.object)
            .where(DO.dataset == F006_UUID)
            .order_by(DO.object)
        )
        rows = session.execute(stmt).all()
        db_data = [
            {'dataset': str(r[0]), 'object': str(r[1])} for r in rows
        ]
        fixture = _load_fixture('dataset_object.json')
        assert fixture == db_data


class TestValuesQuantSummary:
    """VAL-SNAP-004: values_quant summary matches production (2,445,944)."""

    def test_total_count(self) -> None:
        data = _load_fixture('values_quant_summary.json')
        assert data['total'] == 2_445_944

    def test_fiber_descriptors_608811_each(self) -> None:
        data = _load_fixture('values_quant_summary.json')
        fiber_labels = [
            'fiber cross section diameter um min',
            'fiber cross section area um2',
            'fiber cross section diameter um',
            'fiber cross section diameter um max',
        ]
        for label in fiber_labels:
            assert data['breakdown'].get(label) == 608_811, (
                f'{label!r}: expected 608,811, got {data["breakdown"].get(label)}'
            )


class TestValuesCatSummary:
    """VAL-SNAP-005: values_cat summary matches production (608,859)."""

    def test_total_count(self) -> None:
        data = _load_fixture('values_cat_summary.json')
        assert data['total'] == 608_859

    def test_has_axon_fiber_type(self) -> None:
        data = _load_fixture('values_cat_summary.json')
        assert data['breakdown'].get('hasAxonFiberType') == 608_811


class TestInstanceParentCount:
    """instance_parent count matches production."""

    def test_total_count(self) -> None:
        data = _load_fixture('instance_parent_count.json')
        assert data['total'] == 609_389


# ---------------------------------------------------------------------------
# Test: Small table fixtures match production exactly
# ---------------------------------------------------------------------------


class TestSmallTableFixtures:
    """VAL-SNAP-006: Small table fixtures match production exactly."""

    def test_equiv_inst_count(self) -> None:
        data = _load_fixture('equiv_inst.json')
        assert len(data) == 37

    def test_objects_internal_count(self) -> None:
        data = _load_fixture('objects_internal.json')
        assert len(data) == 1

    def test_objects_count(self) -> None:
        """122 objects: 121 linked + 1 dataset object itself."""
        data = _load_fixture('objects.json')
        assert len(data) == 122

    def test_obj_desc_inst_count(self) -> None:
        data = _load_fixture('obj_desc_inst.json')
        assert len(data) == 123

    def test_obj_desc_quant_count(self) -> None:
        data = _load_fixture('obj_desc_quant.json')
        assert len(data) == 1042

    def test_obj_desc_cat_count(self) -> None:
        data = _load_fixture('obj_desc_cat.json')
        assert len(data) == 83

    def test_equiv_inst_matches_db(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        EI = reflected.EquivInst
        VI = reflected.ValuesInst
        stmt = (
            select(EI.left_thing, EI.right_thing)
            .join(VI, EI.left_thing == VI.id)
            .where(VI.dataset == F006_UUID)
            .order_by(EI.left_thing, EI.right_thing)
        )
        rows = session.execute(stmt).all()
        db_data = [
            {'left_thing': r[0], 'right_thing': r[1]} for r in rows
        ]
        fixture = _load_fixture('equiv_inst.json')
        assert fixture == db_data

    def test_objects_internal_matches_db(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        OI = reflected.ObjectsInternal
        stmt = (
            select(
                OI.id, OI.type, OI.dataset,
                OI.updated_transitive, OI.label, OI.curator_note,
            )
            .where(OI.dataset == F006_UUID)
            .order_by(OI.id)
        )
        rows = session.execute(stmt).all()
        db_data = [
            {
                'id': str(r[0]),
                'type': str(r[1]) if r[1] is not None else None,
                'dataset': str(r[2]) if r[2] is not None else None,
                'updated_transitive': str(r[3]) if r[3] is not None else None,
                'label': r[4],
                'curator_note': r[5],
            }
            for r in rows
        ]
        fixture = _load_fixture('objects_internal.json')
        assert fixture == db_data


# ---------------------------------------------------------------------------
# Test: Deterministic extraction
# ---------------------------------------------------------------------------


class TestDeterministicExtraction:
    """VAL-SNAP-007: Fixtures are deterministic across runs."""

    def test_two_runs_produce_identical_files(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """SHA-256 hash comparison of all fixture files across two runs."""
        with tempfile.TemporaryDirectory() as tmpdir1, \
                tempfile.TemporaryDirectory() as tmpdir2:
            extract_f006_snapshot(
                session, Path(tmpdir1), models=reflected,
            )
            extract_f006_snapshot(
                session, Path(tmpdir2), models=reflected,
            )

            files1 = sorted(Path(tmpdir1).glob('*.json'))
            files2 = sorted(Path(tmpdir2).glob('*.json'))

            assert len(files1) == len(files2), (
                f'Different file count: {len(files1)} vs {len(files2)}'
            )

            for f1, f2 in zip(files1, files2):
                assert f1.name == f2.name
                h1 = _sha256(f1)
                h2 = _sha256(f2)
                assert h1 == h2, (
                    f'{f1.name} not deterministic: {h1} != {h2}'
                )


# ---------------------------------------------------------------------------
# Helpers for comparison tests
# ---------------------------------------------------------------------------


def _copy_fixtures(src_dir, dst_dir):
    """Copy all fixture JSON files from src to dst."""
    for f in Path(src_dir).glob('*.json'):
        shutil.copy2(f, Path(dst_dir) / f.name)


def _load_and_save(path, modifier_fn):
    """Load a JSON file, apply modifier_fn, and save back.

    Args:
        path: Path to the JSON file.
        modifier_fn: Callable that receives the loaded data and returns
            the modified data to write back.
    """
    with open(path) as f:
        data = json.load(f)
    data = modifier_fn(data)
    with open(path, 'w') as f:
        json.dump(data, f, sort_keys=True, default=str, indent=2)
        f.write('\n')
    return data


# ---------------------------------------------------------------------------
# Test: Comparison utility -- identical comparison
# ---------------------------------------------------------------------------


class TestComparisonIdentical:
    """VAL-SNAP-008: Comparing a snapshot to itself reports no diffs."""

    def test_is_identical(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Comparing DB against its own fixtures should be identical."""
        result = compare_snapshot(session, FIXTURES_DIR, models=reflected)
        assert result.is_identical

    def test_all_tables_match(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Every table should report is_match=True."""
        result = compare_snapshot(session, FIXTURES_DIR, models=reflected)
        for name, diff in result.tables.items():
            assert diff.is_match, f'{name} has unexpected diffs'

    def test_no_added_removed_modified(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """Full-row tables should have no added, removed, or modified."""
        result = compare_snapshot(session, FIXTURES_DIR, models=reflected)
        for name, diff in result.tables.items():
            if diff.fixture_type == 'full_rows':
                assert not diff.added, f'{name}: unexpected added rows'
                assert not diff.removed, f'{name}: unexpected removed rows'
                assert not diff.modified, f'{name}: unexpected modified rows'

    def test_all_eleven_tables_compared(
        self,
        session: Session,
        reflected: ReflectedModels,
    ) -> None:
        """All 11 fixture files should produce table comparison entries."""
        result = compare_snapshot(session, FIXTURES_DIR, models=reflected)
        assert len(result.tables) == 11


# ---------------------------------------------------------------------------
# Test: Comparison utility -- detects added rows
# ---------------------------------------------------------------------------


class TestComparisonDetectsAddedRows:
    """VAL-SNAP-008: Detects rows in DB not present in fixture.

    To simulate the DB having an extra row, we remove a row from the
    fixture copy.  The comparison should report it as 'added' (present
    in DB but absent from the fixture baseline).
    """

    def test_added_row_detected(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Remove one dataset_object row from fixture → detected as added."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)

        removed_row = None
        def _remove_last(rows):
            nonlocal removed_row
            removed_row = rows.pop()
            return rows

        _load_and_save(tmp_path / 'dataset_object.json', _remove_last)

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['dataset_object']

        assert not result.is_identical
        assert not diff.is_match
        assert len(diff.added) == 1
        assert diff.added[0]['object'] == removed_row['object']

    def test_added_row_count(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Row count reflects the extra DB row."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)
        _load_and_save(
            tmp_path / 'dataset_object.json',
            lambda rows: rows[:-1],
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['dataset_object']
        assert diff.row_count_expected == 120
        assert diff.row_count_actual == 121


# ---------------------------------------------------------------------------
# Test: Comparison utility -- detects removed rows
# ---------------------------------------------------------------------------


class TestComparisonDetectsRemovedRows:
    """VAL-SNAP-008: Detects rows in fixture not present in DB.

    To simulate the DB missing a row, we add a fake row to the fixture
    copy.  The comparison should report it as 'removed' (present in
    fixture but absent from the DB).
    """

    def test_removed_row_detected(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Add fake dataset_object row to fixture → detected as removed."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)
        fake_row = {
            'dataset': F006_UUID,
            'object': '00000000-0000-0000-0000-000000000000',
        }

        _load_and_save(
            tmp_path / 'dataset_object.json',
            lambda rows: rows + [fake_row],
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['dataset_object']

        assert not result.is_identical
        assert not diff.is_match
        assert len(diff.removed) == 1
        assert diff.removed[0]['object'] == fake_row['object']

    def test_removed_row_count(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Row count reflects the extra fixture row."""
        fake_row = {
            'dataset': F006_UUID,
            'object': '00000000-0000-0000-0000-000000000000',
        }
        _copy_fixtures(FIXTURES_DIR, tmp_path)
        _load_and_save(
            tmp_path / 'dataset_object.json',
            lambda rows: rows + [fake_row],
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['dataset_object']
        assert diff.row_count_expected == 122
        assert diff.row_count_actual == 121


# ---------------------------------------------------------------------------
# Test: Comparison utility -- detects modified values
# ---------------------------------------------------------------------------


class TestComparisonDetectsModifiedValues:
    """VAL-SNAP-008: Detects rows with matching PK but different values.

    We change a non-PK value in the fixture copy.  The comparison should
    report the row as 'modified' with old/new value details.
    """

    def test_modified_value_detected(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Change id_type in objects fixture → detected as modified."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)

        original_value = None
        def _change_first_id_type(rows):
            nonlocal original_value
            original_value = rows[0]['id_type']
            rows[0]['id_type'] = 'MODIFIED_VALUE'
            return rows

        _load_and_save(tmp_path / 'objects.json', _change_first_id_type)

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['objects']

        assert not result.is_identical
        assert not diff.is_match
        assert len(diff.modified) == 1

        entry = diff.modified[0]
        assert 'id_type' in entry['changes']
        assert entry['changes']['id_type']['expected'] == 'MODIFIED_VALUE'
        assert entry['changes']['id_type']['actual'] == original_value

    def test_modified_preserves_pk(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Modified entry includes the PK of the changed row."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)
        obj_path = tmp_path / 'objects.json'
        with open(obj_path) as f:
            rows = json.load(f)
        expected_pk = rows[0]['id']
        rows[0]['id_type'] = 'MODIFIED_VALUE'
        with open(obj_path, 'w') as f:
            json.dump(rows, f, sort_keys=True, default=str, indent=2)
            f.write('\n')

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['objects']
        assert diff.modified[0]['pk'] == {'id': expected_pk}


# ---------------------------------------------------------------------------
# Test: Comparison utility -- detects count mismatches
# ---------------------------------------------------------------------------


class TestComparisonDetectsCountMismatch:
    """VAL-SNAP-008: Detects count mismatches in summary fixtures."""

    def test_total_count_mismatch(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Change total in values_inst_summary → detected as mismatch."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)
        _load_and_save(
            tmp_path / 'values_inst_summary.json',
            lambda data: {**data, 'total': data['total'] + 999},
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['values_inst_summary']

        assert not result.is_identical
        assert not diff.is_match
        assert diff.count_expected == 609_390 + 999
        assert diff.count_actual == 609_390

    def test_breakdown_key_mismatch(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Change a breakdown value → detected as breakdown_changed."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)

        def _tweak_breakdown(data):
            data['breakdown']['subject|human'] = 999
            return data

        _load_and_save(
            tmp_path / 'values_inst_summary.json',
            _tweak_breakdown,
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['values_inst_summary']

        assert not diff.is_match
        assert 'subject|human' in diff.breakdown_changed
        assert diff.breakdown_changed['subject|human'] == {
            'expected': 999,
            'actual': 1,
        }

    def test_extra_breakdown_key_detected(
        self,
        session: Session,
        reflected: ReflectedModels,
        tmp_path: Path,
    ) -> None:
        """Add an extra breakdown key to fixture → detected as removed."""
        _copy_fixtures(FIXTURES_DIR, tmp_path)

        def _add_fake_key(data):
            data['breakdown']['fake|nonexistent'] = 42
            return data

        _load_and_save(
            tmp_path / 'values_inst_summary.json',
            _add_fake_key,
        )

        result = compare_snapshot(session, tmp_path, models=reflected)
        diff = result.tables['values_inst_summary']

        assert not diff.is_match
        assert 'fake|nonexistent' in diff.breakdown_removed
        assert diff.breakdown_removed['fake|nonexistent'] == 42
