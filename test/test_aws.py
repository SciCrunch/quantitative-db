"""Tests for AWS RDS schema setup, lookup data, and idempotency.

All tests require the ``--run-aws`` CLI flag (registered in conftest.py).
"""
import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from quantdb.ingest_v2 import (
    F006_UUID,
    extract_f006_from_db,
    ingest_f006_v2,
)
from quantdb.models import reflect_models
from quantdb.utils import dbUri

pytestmark = pytest.mark.aws

# ---- AWS connection details ------------------------------------------------
AWS_HOST = 'troy-quantdb-test.crxhhfokqjgu.us-east-1.rds.amazonaws.com'
AWS_PORT = 5432
AWS_DB = 'postgres'
AWS_USER = 'postgres'

_BIN_DIR = Path(__file__).resolve().parent.parent / 'bin'
_FIXTURES_DIR = Path(__file__).resolve().parent / 'fixtures' / 'f006'


# ---- fixtures --------------------------------------------------------------


@pytest.fixture(scope='module')
def aws_engine():
    """Create a SQLAlchemy engine connected to the AWS RDS instance."""
    engine = create_engine(
        dbUri(
            dbuser=AWS_USER,
            host=AWS_HOST,
            port=AWS_PORT,
            database=AWS_DB,
        ),
        connect_args={'sslmode': 'require'},
    )

    @event.listens_for(engine, 'connect')
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    yield engine
    engine.dispose()


@pytest.fixture(scope='module', autouse=True)
def run_setup_once():
    """Run ``bin/aws_setup`` once before the module's tests execute."""
    result = subprocess.run(
        ['bash', str(_BIN_DIR / 'aws_setup')],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f'aws_setup failed:\nstdout:\n{result.stdout}\n' f'stderr:\n{result.stderr}'


@pytest.fixture(scope='module')
def f006_data_dicts(rebuild_database):
    """Extract all f006 data from local production-dump-restored DB.

    Returns the dict structure from ``extract_f006_from_db()`` with
    string FK labels suitable for ingestion into any target database.
    """
    eng = create_engine(
        dbUri(
            dbuser='postgres',
            host='localhost',
            port=5432,
            database='quantdb_test',
        ),
    )

    @event.listens_for(eng, 'connect')
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    models = reflect_models(engine=eng)
    sess = models.Session()
    try:
        data = extract_f006_from_db(sess, models)
    finally:
        sess.close()
        eng.dispose()
    return data


@pytest.fixture(scope='module')
def aws_models(aws_engine):
    """Reflect quantdb ORM models from the AWS RDS instance."""
    return reflect_models(engine=aws_engine)


@pytest.fixture(scope='module')
def aws_e2e_ingested(aws_engine, aws_models, f006_data_dicts):
    """Run full E2E: teardown existing f006 data, then ingest to AWS.

    (1) Runs ``bin/aws_teardown`` to clean any existing f006 data.
    (2) Ingests extracted data via ``ingest_f006_v2`` and commits.

    Yields the AWS engine for verification queries in tests.
    """
    # Step 1: Teardown any existing f006 data on AWS
    # Generous timeout: deleting 2.4M+ rows over the network can be slow
    td_result = subprocess.run(
        ['bash', str(_BIN_DIR / 'aws_teardown')],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    assert td_result.returncode == 0, (
        f'aws_teardown failed:\nstdout:\n{td_result.stdout}\n' f'stderr:\n{td_result.stderr}'
    )

    # Step 2: Ingest f006 data to AWS with commit
    sess = aws_models.Session()
    try:
        ingest_f006_v2(sess, aws_models, f006_data_dicts)
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()

    yield aws_engine


# ---- tests ------------------------------------------------------------------


class TestSchemaSetup:
    """VAL-AWS-001: Schema setup creates all 20 tables on AWS RDS."""

    def test_all_20_tables_exist(self, aws_engine):
        with aws_engine.connect() as conn:
            result = conn.execute(
                text('SELECT count(*) FROM information_schema.tables' " WHERE table_schema = 'quantdb'")
            )
            count = result.scalar()
            assert count == 20, f'Expected 20 tables, found {count}'

    def test_quantdb_schema_exists(self, aws_engine):
        with aws_engine.connect() as conn:
            result = conn.execute(
                text('SELECT count(*) FROM information_schema.schemata' " WHERE schema_name = 'quantdb'")
            )
            assert result.scalar() == 1


class TestLookupData:
    """VAL-AWS-002: Lookup data loads correctly on AWS."""

    def test_units_um(self, aws_engine):
        """Spot-check: units table has label='um'."""
        with aws_engine.connect() as conn:
            result = conn.execute(text("SELECT count(*) FROM quantdb.units WHERE label = 'um'"))
            assert result.scalar() == 1

    def test_descriptors_inst_nerve(self, aws_engine):
        """Spot-check: descriptors_inst table has label='nerve'."""
        with aws_engine.connect() as conn:
            result = conn.execute(text('SELECT count(*) FROM quantdb.descriptors_inst' " WHERE label = 'nerve'"))
            assert result.scalar() == 1

    def test_aspects_populated(self, aws_engine):
        """Spot-check: aspects table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.aspects')).scalar()
            assert count > 0, 'aspects table is empty'

    def test_descriptors_quant_populated(self, aws_engine):
        """Spot-check: descriptors_quant table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.descriptors_quant')).scalar()
            assert count > 0, 'descriptors_quant table is empty'

    def test_controlled_terms_populated(self, aws_engine):
        """Spot-check: controlled_terms table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.controlled_terms')).scalar()
            assert count > 0, 'controlled_terms table is empty'

    def test_addresses_populated(self, aws_engine):
        """Spot-check: addresses table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.addresses')).scalar()
            assert count > 0, 'addresses table is empty'

    def test_class_parent_populated(self, aws_engine):
        """Spot-check: class_parent table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.class_parent')).scalar()
            assert count > 0, 'class_parent table is empty'

    def test_aspect_parent_populated(self, aws_engine):
        """Spot-check: aspect_parent table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(text('SELECT count(*) FROM quantdb.aspect_parent')).scalar()
            assert count > 0, 'aspect_parent table is empty'


class TestIdempotency:
    """VAL-AWS-003: AWS setup is idempotent."""

    def test_second_run_no_errors(self, aws_engine):
        """Running aws_setup a second time must succeed without errors."""
        result = subprocess.run(
            ['bash', str(_BIN_DIR / 'aws_setup')],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f'Second aws_setup run failed:\nstdout:\n{result.stdout}\n' f'stderr:\n{result.stderr}'
        )

    def test_table_count_unchanged_after_rerun(self, aws_engine):
        """Table count remains 20 after a second setup run."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM information_schema.tables' " WHERE table_schema = 'quantdb'")
            ).scalar()
            assert count == 20

    def test_lookup_data_unchanged_after_rerun(self, aws_engine):
        """Lookup row counts remain the same after a second setup run."""
        with aws_engine.connect() as conn:
            units = conn.execute(text('SELECT count(*) FROM quantdb.units')).scalar()
            aspects = conn.execute(text('SELECT count(*) FROM quantdb.aspects')).scalar()
            descs = conn.execute(text('SELECT count(*) FROM quantdb.descriptors_inst')).scalar()
            assert units > 0
            assert aspects > 0
            assert descs > 0


# ---- E2E ingest + verification tests ----------------------------------------


class TestE2EIngest:
    """VAL-AWS-004: ingest_v2 commits successfully to AWS RDS over SSL."""

    def test_ingest_completed_without_error(self, aws_e2e_ingested):
        """The aws_e2e_ingested fixture proves ingest committed."""
        assert aws_e2e_ingested is not None


class TestE2ECountVerification:
    """VAL-AWS-005: AWS data counts match gold-standard snapshots."""

    def test_values_inst_total(self, aws_e2e_ingested):
        """values_inst count = 609,390."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.values_inst' ' WHERE dataset = :uuid'),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 609_390

    def test_instance_parent_count(self, aws_e2e_ingested):
        """instance_parent count = 609,389."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text(
                    'SELECT count(*)'
                    ' FROM quantdb.instance_parent ip'
                    ' JOIN quantdb.values_inst vi ON ip.id = vi.id'
                    ' WHERE vi.dataset = :uuid'
                ),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 609_389

    def test_dataset_object_count(self, aws_e2e_ingested):
        """dataset_object count = 121."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.dataset_object' ' WHERE dataset = :uuid'),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 121

    def test_values_quant_total(self, aws_e2e_ingested):
        """values_quant count = 2,445,944."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text(
                    'SELECT count(*)'
                    ' FROM quantdb.values_quant vq'
                    ' JOIN quantdb.dataset_object do2'
                    '   ON vq.object = do2.object'
                    ' WHERE do2.dataset = :uuid'
                ),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 2_445_944

    def test_values_cat_total(self, aws_e2e_ingested):
        """values_cat count = 608,859."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text(
                    'SELECT count(*)'
                    ' FROM quantdb.values_cat vc'
                    ' JOIN quantdb.dataset_object do2'
                    '   ON vc.object = do2.object'
                    ' WHERE do2.dataset = :uuid'
                ),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 608_859

    def test_equiv_inst_count(self, aws_e2e_ingested):
        """equiv_inst count = 0 (cross-dataset refs not loaded on AWS)."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text(
                    'SELECT count(*)'
                    ' FROM quantdb.equiv_inst ei'
                    ' JOIN quantdb.values_inst vi'
                    '   ON ei.left_thing = vi.id'
                    ' WHERE vi.dataset = :uuid'
                ),
                {'uuid': F006_UUID},
            ).scalar()
        # All 37 equiv_inst rows reference a cross-dataset that
        # isn't loaded on AWS, so the count is 0 here.
        # The local test (test_ingest_v2.py) proves the full 37.
        assert count == 0

    def test_objects_internal_count(self, aws_e2e_ingested):
        """objects_internal count = 1."""
        with aws_e2e_ingested.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.objects_internal' ' WHERE dataset = :uuid'),
                {'uuid': F006_UUID},
            ).scalar()
        assert count == 1

    def test_values_inst_breakdown(self, aws_e2e_ingested):
        """(type, desc_inst_label) breakdown matches all 7 groups."""
        with aws_e2e_ingested.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT vi.type, di.label, count(*)'
                    ' FROM quantdb.values_inst vi'
                    ' JOIN quantdb.descriptors_inst di'
                    '   ON vi.desc_inst = di.id'
                    ' WHERE vi.dataset = :uuid'
                    ' GROUP BY vi.type, di.label'
                    ' ORDER BY vi.type, di.label'
                ),
                {'uuid': F006_UUID},
            ).all()
        breakdown = {f'{row[0]}|{row[1]}': row[2] for row in rows}

        with open(_FIXTURES_DIR / 'values_inst_summary.json') as f:
            fixture = json.load(f)
        assert breakdown == fixture['breakdown']


class TestE2ESpotCheck:
    """Spot-check AWS data against local gold-standard fixture data."""

    def test_dataset_object_uuids_match_fixture(self, aws_e2e_ingested):
        """All 121 dataset_object UUIDs match the gold-standard fixture."""
        with open(_FIXTURES_DIR / 'dataset_object.json') as f:
            expected = json.load(f)

        with aws_e2e_ingested.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT CAST(dataset AS text),'
                    '       CAST(object AS text)'
                    ' FROM quantdb.dataset_object'
                    ' WHERE dataset = :uuid'
                    ' ORDER BY object'
                ),
                {'uuid': F006_UUID},
            ).all()

        actual = [{'dataset': row[0], 'object': row[1]} for row in rows]
        assert len(actual) == len(expected)
        assert actual == expected

    def test_values_quant_breakdown_matches_fixture(self, aws_e2e_ingested):
        """values_quant per-descriptor breakdown matches gold standard."""
        with open(_FIXTURES_DIR / 'values_quant_summary.json') as f:
            fixture = json.load(f)

        with aws_e2e_ingested.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT dq.label, count(*)'
                    ' FROM quantdb.values_quant vq'
                    ' JOIN quantdb.descriptors_quant dq'
                    '   ON vq.desc_quant = dq.id'
                    ' JOIN quantdb.dataset_object do2'
                    '   ON vq.object = do2.object'
                    ' WHERE do2.dataset = :uuid'
                    ' GROUP BY dq.label'
                    ' ORDER BY dq.label'
                ),
                {'uuid': F006_UUID},
            ).all()

        actual = {row[0]: row[1] for row in rows}
        assert actual == fixture['breakdown']

    def test_values_cat_breakdown_matches_fixture(self, aws_e2e_ingested):
        """values_cat per-descriptor breakdown matches gold standard."""
        with open(_FIXTURES_DIR / 'values_cat_summary.json') as f:
            fixture = json.load(f)

        with aws_e2e_ingested.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT dc.label, count(*)'
                    ' FROM quantdb.values_cat vc'
                    ' JOIN quantdb.descriptors_cat dc'
                    '   ON vc.desc_cat = dc.id'
                    ' JOIN quantdb.dataset_object do2'
                    '   ON vc.object = do2.object'
                    ' WHERE do2.dataset = :uuid'
                    ' GROUP BY dc.label'
                    ' ORDER BY dc.label'
                ),
                {'uuid': F006_UUID},
            ).all()

        actual = {row[0]: row[1] for row in rows}
        assert actual == fixture['breakdown']

    def test_values_quant_sample_has_valid_data(self, aws_e2e_ingested):
        """First 10 values_quant rows have non-null numeric values."""
        with aws_e2e_ingested.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT CAST(vq.value AS text),'
                    '       dq.label,'
                    '       vi.id_formal'
                    ' FROM quantdb.values_quant vq'
                    ' JOIN quantdb.descriptors_quant dq'
                    '   ON vq.desc_quant = dq.id'
                    ' JOIN quantdb.values_inst vi'
                    '   ON vq.instance = vi.id'
                    ' WHERE vq.object IN ('
                    '   SELECT object'
                    '   FROM quantdb.dataset_object'
                    '   WHERE dataset = :uuid'
                    ' )'
                    ' ORDER BY vi.id_formal, dq.label'
                    ' LIMIT 10'
                ),
                {'uuid': F006_UUID},
            ).all()

        assert len(rows) == 10
        for row in rows:
            value_str, desc_label, id_formal = row
            assert value_str is not None, f'Null value for {id_formal}/{desc_label}'
            assert desc_label is not None
            assert id_formal is not None
            # Verify value is numeric
            float(value_str)
