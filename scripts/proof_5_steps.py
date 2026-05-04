import os
import subprocess
from pathlib import Path

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, event

from quantdb.api import make_app
from quantdb.extract_microct import MICROCT_UUID
from quantdb.ingest_microct import (
    _count_microct,
    delete_microct_data,
    ingest_microct,
)
from quantdb.models import reflect_models
from quantdb.utils import dbUri

REPO = Path(__file__).resolve().parent.parent
SQL = REPO / 'sql'
DUMP = REPO / 'resources' / 'quantdb_demo.dump'
DB = 'quantdb_demo'
PG_DUMP = '/opt/homebrew/opt/postgresql@16/bin/pg_dump'
PG_RESTORE = '/opt/homebrew/opt/postgresql@16/bin/pg_restore'
AWS_HOST = 'troy-quantdb-test.crxhhfokqjgu.us-east-1.rds.amazonaws.com'
AWS_DB = 'postgres'
AWS_USER = 'postgres'
DATASET = MICROCT_UUID
OBJ = 'aaaaaaaa-1111-2222-3333-444444444401'
DATA_TABLES = [
    'objects', 'dataset_object', 'values_inst', 'instance_parent',
    'obj_desc_inst', 'obj_desc_quant', 'obj_desc_cat',
    'values_quant', 'values_cat',
]


def psql(sql=None, *, file=None, db='postgres', extra=None):
    cmd = ['psql', '-U', 'postgres', '-h', 'localhost', '-p', '5432',
           '-d', db, '-v', 'ON_ERROR_STOP=on']
    if extra:
        for k, v in extra.items():
            cmd += ['-v', f'{k}={v}']
    cmd += ['-f', str(file)] if file else ['-c', sql]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def set_search_path(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute('SET search_path TO quantdb, public')
    cur.close()


psql(file=SQL / 'postgres.sql', extra={'test_database': DB, 'database': DB})
psql(sql='GRANT "quantdb-test-admin" TO CURRENT_USER;')
psql(sql=f'DROP DATABASE IF EXISTS {DB};')
psql(sql=(
    f"CREATE DATABASE {DB} WITH OWNER='quantdb-test-admin' "
    f"TEMPLATE template0 ENCODING='UTF8' "
    f"LC_COLLATE='C' LC_CTYPE='C';"
))
psql(sql='REVOKE "quantdb-test-admin" FROM CURRENT_USER;')
psql(sql='ALTER ROLE postgres SET search_path = quantdb, public;')
psql(file=SQL / 'schemas.sql', db=DB)
psql(file=SQL / 'tables.sql', db=DB)
psql(file=SQL / 'permissions.sql', db=DB,
     extra={'database': DB, 'perm_user': 'quantdb-test-user'})
psql(file=SQL / 'inserts.sql', db=DB)
psql(file=SQL / 'inserts_microct.sql', db=DB)

engine = create_engine(dbUri('postgres', 'localhost', 5432, DB))
event.listen(engine, 'connect', set_search_path)
models = reflect_models(engine=engine)

PAYLOAD = {
    'session': models.Session(),
    'models': models,
    'data_dicts': {
        'objects': [
            {'id': DATASET, 'id_type': 'dataset', 'id_file': None},
            {'id': OBJ, 'id_type': 'package', 'id_file': 1},
        ],
        'dataset_object': [{'dataset': DATASET, 'object': OBJ}],
        'values_inst': [
            {'dataset': DATASET, 'id_formal': 'sub-X', 'type': 'subject',
             'desc_inst': 'human', 'id_sub': 'sub-X'},
            {'dataset': DATASET, 'id_formal': 'sam-X-1', 'type': 'sample',
             'desc_inst': 'tissue', 'id_sub': 'sub-X', 'id_sam': 'sam-X-1'},
            {'dataset': DATASET, 'id_formal': 'nerve-X-1', 'type': 'below',
             'desc_inst': 'nerve', 'id_sub': 'sub-X', 'id_sam': 'sam-X-1'},
            {'dataset': DATASET, 'id_formal': 'nerve-X-1-slice-0', 'type': 'below',
             'desc_inst': 'nerve-cross-section',
             'id_sub': 'sub-X', 'id_sam': 'sam-X-1'},
        ],
        'instance_parent': [
            {'id': {'dataset': DATASET, 'id_formal': 'sam-X-1'},
             'parent': {'dataset': DATASET, 'id_formal': 'sub-X'}},
            {'id': {'dataset': DATASET, 'id_formal': 'nerve-X-1'},
             'parent': {'dataset': DATASET, 'id_formal': 'sam-X-1'}},
            {'id': {'dataset': DATASET, 'id_formal': 'nerve-X-1-slice-0'},
             'parent': {'dataset': DATASET, 'id_formal': 'nerve-X-1'}},
        ],
        'values_quant': [
            {'value': 1.0, 'value_blob': 1.0, 'object': OBJ,
             'desc_inst': 'nerve-cross-section',
             'desc_quant': 'nerve cross section diameter um',
             'instance': {'dataset': DATASET,
                          'id_formal': 'nerve-X-1-slice-0'}},
        ],
        'values_cat': [],
    },
}
ingest_microct(**PAYLOAD)
PAYLOAD['session'].commit()
PAYLOAD['session'].close()

s = models.Session()
counts = _count_microct(s, models)
assert counts['objects'] >= 2
assert counts['dataset_object'] >= 1
assert counts['values_inst'] >= 4
assert counts['instance_parent'] >= 3
assert counts['values_quant'] >= 1
s.close()

DUMP.parent.mkdir(parents=True, exist_ok=True)
dump_cmd = [PG_DUMP, '--data-only', '-Fc', '-U', 'postgres',
            '-h', 'localhost', '-p', '5432',
            '-d', DB, '-f', str(DUMP)]
for t in DATA_TABLES:
    dump_cmd += ['-t', f'quantdb.{t}']
subprocess.run(dump_cmd, check=True)

env = {**os.environ, 'PGSSLMODE': 'require'}
subprocess.run(['bash', str(REPO / 'bin' / 'aws_setup')],
               check=True, env=env)

aws_engine = create_engine(
    dbUri(AWS_USER, AWS_HOST, 5432, AWS_DB),
    connect_args={'sslmode': 'require'},
)
event.listen(aws_engine, 'connect', set_search_path)
aws_models = reflect_models(engine=aws_engine)

sa = aws_models.Session()
delete_microct_data(sa, aws_models)
sa.commit()
sa.close()

subprocess.run(
    [PG_RESTORE, '--data-only', '--disable-triggers',
     '-U', AWS_USER, '-h', AWS_HOST, '-p', '5432',
     '-d', AWS_DB, str(DUMP)],
    check=True, env=env,
)

os.environ['QUANTDB_DB_HOST'] = AWS_HOST
os.environ['QUANTDB_DB_PORT'] = '5432'
os.environ['QUANTDB_DB_USER'] = AWS_USER
os.environ['QUANTDB_DB_DATABASE'] = AWS_DB
os.environ['PGSSLMODE'] = 'require'

app = make_app(db=SQLAlchemy(), test=False)
client = app.test_client()
r1 = client.get('/api/1//db-name')
assert r1.status_code == 200
assert AWS_DB in r1.get_data(as_text=True)
r2 = client.get('/api/1//classes?include-unused=true')
assert r2.status_code == 200
