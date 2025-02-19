import json
import pathlib
import sys
from collections import defaultdict

import requests
from sparcur import objects as sparcur_objects  # register pathmeta type
from sparcur.paths import Path
from sparcur.utils import PennsieveId as RemoteId
from sparcur.utils import fromJson
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import bindparam
from sqlalchemy.sql import text as sql_text

from quantdb.utils import dbUri, isoformat, log

# FIXME sparcur dependencies, or keep ingest separate

######### start database interaction section


log = log.getChild('ingest')

try:
    if get_ipython().__class__.__name__ == 'ZMQInteractiveShell':
        import sys  # FIXME hack that should be in jupyter-repl env or something

        sys.breakpointhook = lambda: None
except NameError:
    pass


# from interlex.core import getName
class getName:
    class MyBool:
        """python is dumb"""

    def __init__(self):
        self.counter = -1
        self.value_to_name = {}

    def valueCheck(self, value):
        if isinstance(value, dict):
            value = hash(
                frozenset(
                    (k, self.valueCheck(v) if isinstance(v, list) or isinstance(v, dict) else v)
                    for k, v in value.items()
                )
            )
        elif isinstance(value, list):
            value = tuple(self.valueCheck(e) for e in value)
        elif isinstance(value, bool):
            value = self.MyBool, value
        else:
            pass

        return value

    def __call__(self, value, type=None):
        value = self.valueCheck(value)
        if type is not None and (value, type) in self.value_to_name:
            return self.value_to_name[value, type]
        elif type is None and value in self.value_to_name:
            return self.value_to_name[value]
        else:
            self.counter += 1
            name = 'v' + str(self.counter)

            if type is None:
                self.value_to_name[value] = name
            else:
                self.value_to_name[value, type] = name

            return name


# from interlex.core import makeParamsValues
def makeParamsValues(*value_sets, constants=tuple(), types=tuple(), row_types=tuple()):
    # TODO variable sized records and
    # common value names
    if constants and not all(':' in c for c in constants):
        raise ValueError(f'All constants must pass variables in via params {constants}')

    getname = getName()

    params = {}
    if types:
        bindparams = []
        itertypes = (t for ts in types for t in ts)

    elif row_types:
        bindparams = []

    for i, values in enumerate(value_sets):
        # proto_params doesn't need to be a dict
        # values will be reduced when we create params as a dict
        if row_types:
            proto_params = [(tuple(getname(value, type=t) for value, t in zip(row, row_types)), row) for row in values]
        else:
            proto_params = [(tuple(getname(value) for value in row), row) for row in values]

        values_template = ', '.join(
            '(' + ', '.join(constants + tuple(':' + name for name in names)) + ')' for names, _ in proto_params
        )
        yield values_template
        if row_types:
            _done = set()
            for names, values in proto_params:
                for name, value, type in zip(names, values, row_types):
                    params[name] = value
                    if type is not None and name not in _done:
                        bindparams.append(bindparam(name, type_=type))
        else:
            for names, values in proto_params:
                for name, value in zip(names, values):
                    params[name] = value
                    if types:
                        maybe_type = next(itertypes)
                        if maybe_type is not None:
                            bindparams.append(bindparam(name, type_=maybe_type))

    yield params
    if types or row_types:
        yield bindparams  # TODO not sure if there are dupes here


"""
l left
r right
c cardiac not left or right but a branch on its own FIXME might be for central for esophageal
a anterior
p posterior

c cervical
t throacic
a abdominal
"""
sam_ordering = {
    'l': 0,  # left
    'r': 0,  # right
    'c': 1,  # central +cardiac safe to keep at zero since the c index usually come after t+ FIXME means central so it is where both sides merge so have to redo the ordering which will force a v2
    'a': 2,  # anterior
    'p': 2,  # posterior
}
seg_ordering = {
    'c': 0,  # cervical
    't': 1,  # thoracic
    'a': 2,  # abdominal
}


def anat_index(sample):
    # count the number of distinct values less than a given integer
    # create the map

    sam, sam_id, seg, seg_id = sample.split('-')
    # FIXME bad becase left and right are unstable and we don't care about this, we just want relative to max possible
    # don't do this with sort
    sam_ind = sam_ordering[sam_id]
    for k, v in seg_ordering.items():
        if seg_id.startswith(k):
            prefix = k
            seg_ind = v
            break
    else:
        if sam_id == 'c':
            # print('c sample', sample)
            # rest = int(''.join(_ for _ in seg_id if _.isdigit()))
            rest = int(seg_id[:-1])
            suffix = int(seg_id[-1].encode().hex())
            return sam_ind, 0, rest, suffix
        else:
            msg = f'unknown seg {sample}'
            print(msg)  # FIXME TODO logging
            # raise ValueError(msg)
            # return int(f'{sam_ind}000')
            return sam_ind, 0, 0, 0

    rest = int(seg_id[len(prefix) :])  # FIXME this convention is not always followed
    comps = sam_ind, seg_ind, rest, 0
    # return int(f'{sam_ind}{seg_ind}{rest:0>2d}')
    return comps


def pps(path_structure):
    if len(path_structure) == 6:
        # FIXME utter hack
        top, subject, sam_1, segment, modality, file = path_structure
    elif len(path_structure) == 5:
        top, subject, sam_1, segment, file = path_structure
        modality = None  # FIXME from metadata sample id
        if file.endswith('.jpx') and ('9um' in file or '36um' in file):
            modality = 'microct'
        else:
            raise NotImplementedError(path_structure)
    else:
        raise NotImplementedError(path_structure)

    p1 = sam_1, subject  # child, parent to match db convention wasDerivedFrom
    p2 = segment, sam_1
    return {
        'parents': (p1, p2),
        'subject': subject,
        'sample': segment,
        'modality': modality,
        # note that because we do not convert to a single value we cannot include raw_anat_index in the qdb but that's ok
        'raw_anat_index_v2': anat_index(segment),
    }


def pps123(path_structure):
    if len(path_structure) == 4:
        dp, sub, sam, file = path_structure
    else:
        breakpoint()
        raise NotImplementedError(path_structure)

    subject = sub
    sample = f'sam-{sub}_{sam}'
    p1 = sample, subject
    return {
        'parents': (p1,),
        'subject': subject,
        'sample': sample,
    }


def ext_pmeta(j, _pps=pps):
    out = {}
    out['dataset'] = j['dataset_id']
    out['object'] = j['remote_id']
    out['file_id'] = (
        j['file_id'] if 'file_id' in j else int(j['uri_api'].rsplit('/')[-1])
    )  # XXX old pathmeta schema that didn't include file id
    ps = pathlib.Path(j['dataset_relative_path']).parts
    [p for p in ps if p.startswith('sub-') or p.startswith('sam-')]
    out.update(_pps(ps))
    return out


def ext_pmeta123(j):
    return ext_pmeta(j, _pps=pps123)


class Queries:
    def __init__(self, session):
        self.session = session

    def address_from_fadd_type_fadd(self, fadd_type, fadd):
        # FIXME multi etc.
        params = dict(fadd_type=fadd_type, fadd=fadd)
        res = [
            i
            for i, in self.session.execute(
                sql_text('select * from address_from_fadd_type_fadd(:fadd_type, :fadd)'), params
            )
        ]
        if res:
            out = res[0]
            if out is None:
                raise ValueError(f'needed a result here {params}')
            else:
                return out

    def desc_inst_from_label(self, label):
        # FIXME multi etc.
        params = dict(label=label)
        res = [i for i, in self.session.execute(sql_text('select * from desc_inst_from_label(:label)'), params)]
        if res:
            out = res[0]
            if out is None:
                raise ValueError(f'needed a result here {params}')
            else:
                return out

    def desc_quant_from_label(self, label):
        # FIXME multi etc.
        params = dict(label=label)
        res = [i for i, in self.session.execute(sql_text('select * from desc_quant_from_label(:label)'), params)]
        if res:
            out = res[0]
            if out is None:
                raise ValueError(f'needed a result here {params}')
            else:
                return out

    def desc_cat_from_label_domain_label(self, label, domain_label):
        # FIXME multi etc.
        params = dict(label=label, domain_label=domain_label)
        res = [
            i
            for i, in self.session.execute(
                sql_text('select * from desc_cat_from_label_domain_label(:label, :domain_label)'), params
            )
        ]
        if res:
            out = res[0]
            if out is None:
                raise ValueError(f'needed a result here {params}')
            else:
                return out

    def cterm_from_label(self, label):
        # FIXME multi etc.
        params = dict(label=label)
        res = [i for i, in self.session.execute(sql_text('select * from cterm_from_label(:label)'), params)]
        if res:
            out = res[0]
            if out is None:
                raise ValueError(f'needed a result here {params}')
            else:
                return out

    def insts_from_dataset(self, dataset):
        return list(self.session.execute(sql_text('select * from insts_from_dataset(:dataset)'), dict(dataset=dataset)))

    def insts_from_dataset_ids(self, dataset, ids):
        return list(
            self.session.execute(
                sql_text('select * from insts_from_dataset_ids(:dataset, :ids)'), dict(dataset=dataset, ids=ids)
            )
        )


class InternalIds:
    def __init__(self, queries):
        q = queries
        self._q = queries

        self.addr_suid = q.address_from_fadd_type_fadd('tabular-header', 'id_sub')
        self.addr_said = q.address_from_fadd_type_fadd('tabular-header', 'id_sam')
        self.addr_spec = q.address_from_fadd_type_fadd('tabular-header', 'species')
        self.addr_saty = q.address_from_fadd_type_fadd('tabular-header', 'sample_type')

        self.addr_tmod = q.address_from_fadd_type_fadd('tabular-header', 'modality')

        self.addr_NFasc = q.address_from_fadd_type_fadd('tabular-header', 'NFasc')  # FIXME not really a tabular source
        self.addr_dNerve_um = q.address_from_fadd_type_fadd(
            'tabular-header', 'dNerve_um'
        )  # FIXME not really a tabular source
        self.addr_laterality = q.address_from_fadd_type_fadd('tabular-header', 'laterality')
        self.addr_level = q.address_from_fadd_type_fadd('tabular-header', 'level')

        self.addr_dFasc_um_idx = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/#int/dFasc_um'
        )  # FIXME not really a json source, FIXME how to distinguish the index from the value
        self.addr_dFasc_um_value = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/#int/dFasc_um/#int'
        )  # FIXME not really a json source

        # addr_trai = address_from_fadd_type_fadd('tabular-header', 'raw_anat_index')
        # addr_tnai = address_from_fadd_type_fadd('tabular-header', 'norm_anat_index')
        # addr_context = address_from_fadd_type_fadd('context', '#/path-metadata/{index of match remote_id}/dataset_relative_path')  # XXX this doesn't do what we want, I think what we really would want in these contexts are objects_internal that reference the file system state for a given updated snapshot, that is the real "object" that corresponds to the path-metadata.json that we are working from

        # addr_jpmod = address_from_fadd_type_fadd('json-path-with-types', '#/#int/modality')
        # addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/#int/anat_index')
        # addr_jpnai = address_from_fadd_type_fadd('json-path-with-types', '#/#int/norm_anat_index')

        self.addr_jpdrp = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path'
        )

        # XXX these are more accurate if opaque
        self.addr_jpmod = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-modality'
        )
        # addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-raw-anat-index')
        self.addr_jpnai1 = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1'
        )
        self.addr_jpnain1 = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-min'
        )
        self.addr_jpnaix1 = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-max'
        )
        self.addr_jpnai = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2'
        )
        self.addr_jpnain = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2-min'
        )
        self.addr_jpnaix = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2-max'
        )
        self.addr_jpsuid = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-subject-id'
        )
        self.addr_jpsaid = q.address_from_fadd_type_fadd(
            'json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-sample-id'
        )

        self.addr_jpspec = q.address_from_fadd_type_fadd('json-path-with-types', '#/local/tom-made-it-up/species')
        self.addr_jpsaty = q.address_from_fadd_type_fadd('json-path-with-types', '#/local/tom-made-it-up/sample_type')

        # future version when we actually have the metadata files
        # addr_jpmod = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/manifest/#int/modality')
        # addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/raw_anat_index')
        # addr_jpnai = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/norm_anat_index')
        # addr_jpsuid = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/subjects/#int/id_sub')
        # addr_jpsaid = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/id_sam')

        self.addr_const_null = q.address_from_fadd_type_fadd('constant', None)

        self.qd_nvlai1 = q.desc_quant_from_label('vagus level anatomical location distance index normalized v1')
        self.qd_nvlain1 = q.desc_quant_from_label('vagus level anatomical location distance index normalized v1 min')
        self.qd_nvlaix1 = q.desc_quant_from_label('vagus level anatomical location distance index normalized v1 max')

        # qd_rai = desc_quant_from_label('reva ft sample anatomical location distance index raw')
        self.qd_nai1 = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v1')
        self.qd_nain1 = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v1 min')
        self.qd_naix1 = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v1 max')

        self.qd_nai = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v2')
        self.qd_nain = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v2 min')
        self.qd_naix = q.desc_quant_from_label('reva ft sample anatomical location distance index normalized v2 max')

        self.qd_count = q.desc_quant_from_label('count')  # FIXME see count-of-sheep-in-field-at-time issue
        self.qd_nerve_cs_diameter_um = q.desc_quant_from_label('nerve cross section diameter um')
        self.qd_fasc_cs_diameter_um = q.desc_quant_from_label('fascicle cross section diameter um')

        self.cd_mod = q.desc_cat_from_label_domain_label('hasDataAboutItModality', None)
        self.cd_obj = q.desc_cat_from_label_domain_label('hasAssociatedObject', None)
        self.cd_bot = q.desc_cat_from_label_domain_label(
            'bottom', None
        )  # we just need something we can reference that points to null so we can have a refernce to all the objects, XXX but it can't actually be bottom because bottom by definition relates no entities

        self.id_human = q.desc_inst_from_label('human')
        self.id_nerve = q.desc_inst_from_label('nerve')
        self.id_nerve_volume = q.desc_inst_from_label('nerve-volume')
        self.id_nerve_cross_section = q.desc_inst_from_label('nerve-cross-section')
        self.id_fascicle_cross_section = q.desc_inst_from_label('fascicle-cross-section')
        self.luid = {
            'human': self.id_human,
            'nerve': self.id_nerve,
            'nerve-volume': self.id_nerve_volume,
            'nerve-cross-section': self.id_nerve_cross_section,
            'fascicle-cross-section': self.id_fascicle_cross_section,
        }

        self.ct_mod = q.cterm_from_label('microct')  # lol ct ct
        self.ct_hack = q.cterm_from_label('hack-associate-some-value')
        self.luct = {
            'ct-hack': self.ct_hack,
            'microct': self.ct_mod,
        }


class Inserts:
    # TODO
    pass


def ingest(dataset_uuid, extract_fun, session, commit=False, dev=False, values_args=None, **kwargs):
    """generic ingest workflow
    this_dataset_updated_uuid might not be needed in future,
    add a kwarg to control it maybe?
    """

    ocdn = ' ON CONFLICT DO NOTHING' if dev else ''

    if extract_fun is None and values_args is None:
        raise TypeError('need one of extract_fun or values_args')

    (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    ) = (
        extract_fun(dataset_uuid, **kwargs) if values_args is None else values_args
    )

    q = Queries(session)
    i = InternalIds(q)

    # no dependencies to generate, but insert has to come after the dataset has been inserted (minimally)
    values_instances = make_values_instances(i)

    res0 = session.execute(
        sql_text('INSERT INTO objects (id, id_type) VALUES (:id, :id_type) ON CONFLICT DO NOTHING'),
        dict(id=dataset_uuid, id_type='dataset'),
    )

    # oh dear https://stackoverflow.com/questions/34708509/how-to-use-returning-with-on-conflict-in-postgresql
    if updated_transitive:
        res1 = session.execute(
            sql_text(
                "WITH ins AS (INSERT INTO objects_internal (type, dataset, updated_transitive, label) VALUES ('path-metadata', :dataset, :updated_transitive, :label) ON CONFLICT DO NOTHING RETURNING id) SELECT id FROM ins UNION ALL SELECT id FROM objects_internal WHERE type = 'path-metadata' AND dataset = :dataset AND updated_transitive = :updated_transitive"
            ),  # TODO see whether we actually need union all here or whether union by itself is sufficient
            dict(
                dataset=dataset_uuid,
                updated_transitive=updated_transitive,
                label=f'test-load-for-f001 {isoformat(updated_transitive)}',
            ),
        )

        # it is better to use this approach for all top down information
        # just assume that it is coming from some combination of the metadata files and the file system
        # and leave it at that, prov can be chased down later if needed
        this_dataset_updated_uuid = [_ for _, in res1][0]
    else:
        this_dataset_updated_uuid = None

    void = make_void(this_dataset_updated_uuid, i)
    vocd = make_vocd(this_dataset_updated_uuid, i)
    voqd = make_voqd(this_dataset_updated_uuid, i)

    if updated_transitive:
        res1_1 = session.execute(
            sql_text(
                'INSERT INTO objects (id, id_type, id_internal) VALUES (:id, :id_type, :id) ON CONFLICT DO NOTHING'
            ),  # FIXME bad ocdn here
            dict(id=this_dataset_updated_uuid, id_type='quantdb'),
        )

    vt, params = makeParamsValues(values_objects)
    session.execute(sql_text(f'INSERT INTO objects (id, id_type, id_file) VALUES {vt}{ocdn}'), params)

    vt, params = makeParamsValues(values_dataset_object)
    session.execute(sql_text(f'INSERT INTO dataset_object (dataset, object) VALUES {vt}{ocdn}'), params)

    vt, params = makeParamsValues(values_instances)
    session.execute(
        sql_text(f'INSERT INTO values_inst (dataset, id_formal, type, desc_inst, id_sub, id_sam) VALUES {vt}{ocdn}'),
        params,
    )

    # inserts that depend on instances having already been inserted
    # ilt = q.insts_from_dataset_ids(dataset_uuid, [f for d, f, *rest in values_instances])
    # get all instances in a dataset since values_inst only includes instances we plan to insert
    # not those that were already inserted that we want to add values for
    ilt = q.insts_from_dataset(dataset_uuid)
    luinst = {(str(dataset), id_formal): id for id, dataset, id_formal in ilt}
    values_parents = make_values_parents(luinst)
    values_cv = make_values_cat(this_dataset_updated_uuid, i, luinst)
    values_qv = make_values_quant(this_dataset_updated_uuid, i, luinst)

    vt, params = makeParamsValues(values_parents)
    session.execute(sql_text(f'INSERT INTO instance_parent VALUES {vt}{ocdn}'), params)

    vt, params = makeParamsValues(void)
    session.execute(
        sql_text(f'INSERT INTO obj_desc_inst (object, desc_inst, addr_field, addr_desc_inst) VALUES {vt}{ocdn}'), params
    )

    if vocd:
        vt, params = makeParamsValues(vocd)
        session.execute(sql_text(f'INSERT INTO obj_desc_cat (object, desc_cat, addr_field) VALUES {vt}{ocdn}'), params)

    if voqd:
        vt, params = makeParamsValues(voqd)
        session.execute(
            sql_text(f'INSERT INTO obj_desc_quant (object, desc_quant, addr_field) VALUES {vt}{ocdn}'), params
        )

    if values_cv:
        vt, params = makeParamsValues(values_cv)
        session.execute(
            sql_text(
                f'INSERT INTO values_cat (value_open, value_controlled, object, desc_inst, desc_cat, instance) VALUES {vt}{ocdn}'
            ),
            params,
        )

    if values_qv:
        vt, params, bindparams = makeParamsValues(
            # FIXME LOL the types spec here is atrocious ... but it does work ...
            # XXX and barring the unfortunate case, which we have now encountered  where
            # now fixed in the local impl
            values_qv,
            row_types=(None, None, None, None, None, JSONB),
        )

        t = sql_text(
            f'INSERT INTO values_quant (value, object, desc_inst, desc_quant, instance, value_blob) VALUES {vt}{ocdn}'
        )
        tin = t.bindparams(*bindparams)
        session.execute(tin, params)

    if commit:
        session.commit()


def extract_reva_ft(dataset_uuid, source_local=False, visualize=True):
    if source_local:
        with open(
            pathlib.Path(
                f'~/.local/share/sparcur/export/datasets/{dataset_uuid}/LATEST/path-metadata.json'
            ).expanduser(),
            'rt',
        ) as f:
            blob = json.load(f)

    else:
        resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')

        try:
            blob = resp.json()
        except Exception as e:
            breakpoint()
            raise e

    for j in blob['data']:
        j['type'] = 'pathmeta'

    ir = fromJson(blob)

    updated_transitive = max([i['timestamp_updated'] for i in ir['data'][1:]])  # 1: to skip the dataset object itself

    jpx = [r for r in ir['data'] if 'mimetype' in r and r['mimetype'] == 'image/jpx']

    exts = [ext_pmeta(j) for j in jpx]
    # hrm = sorted(exts, key=lambda j: j['raw_anat_index'])
    # max_rai  = max([e['raw_anat_index'] for e in exts])
    # import math
    # log_max_rai = math.log10(max_rai)

    # normalize the index by mapping distinct values to the integers
    nondist = sorted([e['raw_anat_index_v2'] for e in exts])
    lin_distinct = {v: i for i, v in enumerate(sorted(set([e['raw_anat_index_v2'] for e in exts])))}
    max_distinct = len(lin_distinct)
    mdp1 = max_distinct + 0.1  # to simplify adding overlap

    dd = defaultdict(list)
    for e in exts:
        # e['norm_anat_index'] = math.log10(e['raw_anat_index']) / log_max_rai
        pos = lin_distinct[e['raw_anat_index_v2']]
        e['norm_anat_index_v2'] = (pos + 0.55) / mdp1
        e['norm_anat_index_v2_min'] = pos / mdp1
        e['norm_anat_index_v2_max'] = (
            pos + 1.1
        ) / mdp1  # ensure there is overlap between section for purposes of testing
        # TODO norm_anat_index_min
        # TODO norm_anat_index_max
        dd[e['dataset'], e['sample']].append(e)
    inst_obj_index = dict(dd)

    max_nai = max([e['norm_anat_index_v2'] for e in exts])
    min_nain = min([e['norm_anat_index_v2_min'] for e in exts])
    max_naix = max([e['norm_anat_index_v2_max'] for e in exts])

    if visualize:
        mexts = []
        done = set()
        for e in exts:
            if e['sample'] not in done:
                mexts.append(e)
                done.add(e['sample'])

        _exts = exts
        exts = mexts
        x = list(range(len(exts)))
        # ry = sorted([e['raw_anat_index'] for e in exts])
        idy = [b for a, b in sorted([(e['norm_anat_index_v2'], e['sample']) for e in exts])]
        ny = sorted([e['norm_anat_index_v2'] for e in exts])
        nyn = sorted([e['norm_anat_index_v2_min'] for e in exts])
        nyx = sorted([e['norm_anat_index_v2_max'] for e in exts])
        nnx = list(zip(nyn, nyx))
        import pylab as plt
        import seaborn

        # plt.figure()
        # seaborn.scatterplot(x=x, y=ry)
        plt.figure()
        # end = 10
        end = len(x)
        seaborn.scatterplot(x=x[:end], y=ny[:end], label='inst')
        seaborn.scatterplot(x=x[:end], y=nyn[:end], label='min')
        seaborn.scatterplot(x=x[:end], y=nyx[:end], label='max')
        _sid = blob['data'][0]['basename'].split('-')[-1].strip()
        # if _sid == 'f003':
        # breakpoint()
        plt.title(f'norm-anat-index-v2 for {_sid}')
        plt.xlabel('nth sample')
        plt.ylabel('normalized anatomical index v2')
        plt.legend(loc='upper left')
        # plt.savefig(f'ft-norm-anat-index-v2-{dataset_uuid[:4]}.png')
        plt.savefig(f'ft-norm-anat-index-v2-{_sid}.png')
        exts = _exts

    datasets = {i.uuid: {'id_type': i.type} for e in exts if (i := e['dataset'])}

    packages = {
        i.uuid: {
            'id_type': i.type,
            'id_file': e['file_id'],
        }
        for e in exts
        if (i := e['object'])
    }

    objects = {**datasets, **packages}
    dataset_object = list(set((d.uuid, o.uuid) for e in exts if (d := e['dataset']) and (o := e['object'])))

    subjects = {
        k: {
            'type': 'subject',
            'desc_inst': 'human',
            'id_sub': k[1],
        }
        for k in sorted(set((e['dataset'], e['subject']) for e in exts))
    }
    segments = {
        k[:2]: {
            'type': 'sample',  # FIXME vs below ???
            'desc_inst': 'nerve-volume',  # FIXME should this be nerve-segment and then we use nerve-volume for the 1:1 with files?
            'id_sub': k[-1],
            'id_sam': k[1],
        }
        for k in sorted(set((e['dataset'], e['sample'], e['subject']) for e in exts))
    }
    parents = sorted(set((e['dataset'],) + p for e in exts for p in e['parents']))
    sam_other = {
        p[:2]: {'type': 'sample', 'desc_inst': 'nerve', 'id_sub': p[-1], 'id_sam': p[1]}
        for p in parents
        if p[:2] not in segments
    }
    samples = {**segments, **sam_other}
    instances = {**subjects, **samples}

    values_objects = [
        (i, o['id_type'], o['id_file'] if 'id_file' in o else None)
        for i, o in objects.items()
        if o['id_type'] != 'dataset'  # already did it above
    ]
    values_dataset_object = dataset_object

    def make_values_instances(i):
        values_instances = [
            (
                d.uuid,
                f,
                inst['type'],
                i.luid[inst['desc_inst']],
                inst['id_sub'] if 'id_sub' in inst else None,
                inst['id_sam'] if 'id_sam' in inst else None,
            )
            for (d, f), inst in instances.items()
        ]

        return values_instances

    def make_values_parents(luinst):
        """need the lookup for instances"""
        values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
        return values_parents

    # XXX REMINDER an object descriptor pair can be associated with an arbitrary number of measured instances
    # BUT that mapping only appears when there is _something_ in the qv or cv tables so we need an object
    # desc_inst pair, and an object cat or quant desc pair otherwise our constraints are violated
    # when there is only a single (or zero) records per object then we just create one so that the association
    # to a an instance can proceed, even if the mapping of that instance is from an external source
    # XXX the external source is part of the issue I think
    def make_void(this_dataset_updated_uuid, i):
        void = [  # FIXME this is rather annoying because you have to list all expected types in advance, but I guess that is what we want
            (this_dataset_updated_uuid, i.id_human, i.addr_jpsuid, i.addr_jpspec),
            (this_dataset_updated_uuid, i.id_nerve, i.addr_jpsaid, i.addr_jpsaty),
            (this_dataset_updated_uuid, i.id_nerve_volume, i.addr_jpsaid, i.addr_jpsaty),
            # FIXME what about manifests? those link metadata as an extra hop ... everything meta related needs to come from combined object metadata ???
            # that would certainly make more sense than the nonsense that is going on here, it would simplify the referencing for all the topdown
            # information that we have but it sort of obscures sources, however this _is_ contextual info ... sigh
            # XXX the other option would just be to just put the darned files in the instance measured table :/ because we do have data about them
            # annoying :/
            # + [(i, 'nerve-volume', addr_context) for i in packages]
        ] + [
            (
                o,
                i.id_nerve_volume,
                i.addr_const_null,
                None,
            )  # XXX FIXME this is the only way I can think to do this right now ?
            for o, b in objects.items()
            if b['id_type'] == 'package'
        ]

        return void

    def make_vocd(this_dataset_updated_uuid, i):
        vocd = [
            # FIXME this reveals that there are cases where we may not have void for a single file or that the id comes from context and is not embedded
            # figuring out how to turn that around is going to take a bit of thinking
            (this_dataset_updated_uuid, i.cd_mod, i.addr_jpmod),
        ] + [
            (o, i.cd_obj, i.addr_const_null)  # XXX FIXME this is the only way I can think to do this right now ?
            for o, b in objects.items()
            if b['id_type'] == 'package'
        ]

        return vocd

    def make_voqd(this_dataset_updated_uuid, i):
        voqd = [  # FIXME this isn't quite right, we should just do it to the segments and pretend it is from the samples file I think?
            # FIXME addr_aspect and addr_unit are ... implicit, there is no conditional dispatch but the choice of the constant quantative descriptor comes from ... tgbugs? or what? I think we just leave it as null because it is a constant across all fields, but maybe we just use constant null? but why bother in that case?
            (this_dataset_updated_uuid, i.qd_nai, i.addr_jpnai),
            (
                this_dataset_updated_uuid,
                i.qd_nain,
                i.addr_jpnain,
            ),  # XXX FIXME is this really an aggregation type in this case? I guess it technically if the sample space is over all the points inside the segment or something
            (this_dataset_updated_uuid, i.qd_naix, i.addr_jpnaix),
        ]
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        # obj_index = {e['object']: e for e in exts}
        values_cv = [
            # value_open, value_controlled, object, desc_inst, desc_cat
            (
                e[k],
                i.luct[e[k]],
                this_dataset_updated_uuid,
                # e['object'].uuid,  # FIXME still not right this comes from the updated latest
                i.id_nerve_volume,
                cd,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[e['dataset'].uuid, e['sample']],  # get us the instance
            )
            for e in exts
            for k, cd in (('modality', i.cd_mod),)
        ] + [
            (
                None,
                i.ct_hack,
                e['object'].uuid,
                i.id_nerve_volume,
                i.cd_obj,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[e['dataset'].uuid, e['sample']],  # get us the instance
            )
            for e in exts
        ]
        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        values_qv = [
            # value, object, desc_inst, desc_quant, inst, value_blob
            (
                e[k],
                # e['object'].uuid,  # FIXME TODO we could fill this here but we choose to use this_dataset_updated_uuid instead I think
                this_dataset_updated_uuid,
                i.id_nerve_volume,
                qd,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[e['dataset'].uuid, e['sample']],  # get us the instance
                e[k],
            )
            for e in exts
            for k, qd in (
                # ('raw_anat_index', qd_rai),  # XXX this is a bad place to store object -> field -> qd mappings also risks mismatch on address
                ('norm_anat_index_v2', i.qd_nai),
                ('norm_anat_index_v2_min', i.qd_nain),
                ('norm_anat_index_v2_max', i.qd_naix),
            )
        ]
        return values_qv

    return (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    )

    # this is where things get annoying with needing selects on instance measured


def values_objects_from_objects(objects):
    return [
        (i, o['id_type'], o['id_file'] if 'id_file' in o else None)
        for i, o in objects.items()
        if o['id_type'] != 'dataset'  # already did it above
    ]


def ext_values(exts):
    datasets = {i.uuid: {'id_type': i.type} for e in exts if (i := e['dataset'])}

    packages = {
        i.uuid: {
            'id_type': i.type,
            'id_file': e['file_id'],
        }
        for e in exts
        if (i := e['object'])
    }

    objects = {**datasets, **packages}
    dataset_object = list(set((d.uuid, o.uuid) for e in exts if (d := e['dataset']) and (o := e['object'])))

    subjects = {
        k: {
            'type': 'subject',
            'desc_inst': 'human',  # FIXME hardcoded
            'id_sub': k[1],
        }
        for k in sorted(set((e['dataset'], e['subject']) for e in exts))
    }
    parents = sorted(set((e['dataset'],) + p for e in exts for p in e['parents']))

    samples = {
        k[:2]: {
            'type': 'sample',
            'desc_inst': 'nerve-cross-section',  # FIXME hardcoded
            'id_sub': k[-1],
            'id_sam': k[1],
        }
        for k in sorted(set((e['dataset'], e['sample'], e['subject']) for e in exts))
    }

    instances = {**subjects, **samples}

    values_objects = values_objects_from_objects(objects)
    values_dataset_object = dataset_object

    return instances, parents, objects, values_objects, values_dataset_object


def extract_demo_jp2(dataset_uuid, source_local=False):
    # this is a 1.2.3 dataset so a bit different

    resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')

    try:
        blob = resp.json()
    except Exception as e:
        breakpoint()
        raise e

    for j in blob['data']:
        j['type'] = 'pathmeta'

    ir = fromJson(blob)

    updated_transitive = max([i['timestamp_updated'] for i in ir['data'][1:]])  # 1: to skip the dataset object itself

    jp2 = [r for r in ir['data'] if 'mimetype' in r and r['mimetype'] == 'image/jp2']

    exts = [ext_pmeta123(j) for j in jp2]

    instances, parents, objects, values_objects, values_dataset_object = ext_values(exts)

    def make_values_instances(i):
        values_instances = [
            (
                d.uuid,
                f,
                inst['type'],
                i.luid[inst['desc_inst']],
                inst['id_sub'] if 'id_sub' in inst else None,
                inst['id_sam'] if 'id_sam' in inst else None,
            )
            for (d, f), inst in instances.items()
        ]

        return values_instances

    def make_values_parents(luinst):
        """need the lookup for instances"""
        values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        # we don't derive anything from the dataset updated uuid so nothing goes here
        void = [
            (o, i.id_nerve_cross_section, i.addr_const_null, None)
            for o, b in objects.items()
            if b['id_type'] == 'package'
        ]
        return void

    def make_vocd(this_dataset_updated_uuid, i):
        # we don't derive anything from the dataset updated uuid so nothing goes here
        vocd = [(o, i.cd_obj, i.addr_const_null) for o, b in objects.items() if b['id_type'] == 'package']
        return vocd

    def make_voqd(this_dataset_updated_uuid, i):
        voqd = []  # no quant for this load right now
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        # we don't derive anything from the dataset updated uuid so nothing goes here
        values_cv = [
            (
                None,
                i.ct_hack,
                e['object'].uuid,
                i.id_nerve_cross_section,
                i.cd_obj,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[e['dataset'].uuid, e['sample']],  # get us the instance
            )
            for e in exts
        ]
        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        values_qv = []
        return values_qv

    return (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    )


import augpathlib as aug
import scipy
from sparcur.datasets import SamplesFilePath


def extract_demo(dataset_uuid, source_local=True):
    dataset_id = RemoteId('dataset:' + dataset_uuid)
    _dsp = (
        '/mnt/str/tom/sparc-datasets/55c5b69c-a5b8-4881-a105-e4048af26fa5/SPARC/'
        'Quantified morphology of the human vagus nerve with anti-claudin-1/'
    )
    p = _dsp + 'derivative/CadaverVNMorphology_OutputMetrics.mat'
    _p = aug.AugmentedPath(_dsp + 'samples.xlsx')
    sp = SamplesFilePath(_p)
    ap = Path(p)
    obj_uuid = ap.cache.meta.id.split(':')[-1]
    obj_file_id = ap.cache.meta.file_id
    m = scipy.io.loadmat(p)
    m.keys()
    ks = 'NFasc', 'dFasc_um', 'dNerve_um', 'laterality', 'level', 'sex', 'sub_sam'
    # so insanely dFasc_um and dNerve_um claim dtype('<f8') but store float64 internally ???
    fks = (
        (lambda a: int(a[0])),
        (lambda a: a.tolist()),
        (lambda a: float(a[0])),
        (lambda s: str(s)),
        (lambda s: str(s)),
        (lambda s: str(s)),
        (lambda s: str(s)),
    )

    def level_to_vdd(level):
        if level == 'C':  # cervical
            return {
                'vd': 0.05,  # FIXME this is a bit different than the reva ft case because min and max are actually uncertainty not a true range ???
                'vd-min': 0,
                'vd-max': 0.1,
                'level': 'cervical-vagus',  # TODO cateogorical value
            }

        elif level == 'A':  # abdominal
            return {
                'vd': 0.75,
                'vd-min': 0.5,
                'vd-max': 1,
                'level': 'abdominal-vagus',  # TODO cateogorical value
            }
        else:
            msg = f'unknown vagus level {level}'
            raise NotImplementedError(msg)

    sane_data = [{k: fk(v[0]) for k, fk, v in zip(ks, fks, _)} for _ in zip(*[m[k][0] for k in ks])]
    instances = {}
    parents = []
    nerve_qvs = []
    fasc_qvs = []
    for sd in sane_data:
        ss = sd['sub_sam']
        ss_prefix = ss[0]
        if ss_prefix != 'C':
            continue

        subject_n, sample_n = ss[1:].split('-')
        id_sub = f'sub-{subject_n}'
        id_sam = f'sam-sub-{subject_n}_sam-{sample_n}'
        instances[(dataset_id, id_sam)] = {  # needed for luinst but no inserted
            'type': 'sample',
            'desc_inst': 'nerve-cross-section',
            'id_sub': id_sub,
            'id_sam': id_sam,
        }
        vdd = level_to_vdd(sd['level'])
        nerve_qvs.append(
            {
                **vdd,
                'id_formal': id_sam,
                'desc_inst': 'nerve-cross-section',
                'diameter-um': sd['dNerve_um'],
                'number-of-fascicles': sd['NFasc'],
            }
        )

        for i, fdum in enumerate(sd['dFasc_um']):
            id_formal = f'fasc-{id_sam}-{i}'
            parents.append((dataset_id, id_formal, id_sam))
            instances[(dataset_id, id_formal)] = {
                'type': 'below',
                'desc_inst': 'fascicle-cross-section',
                'id_sub': id_sub,
                'id_sam': id_sam,
            }
            fasc_qvs.append(
                {
                    **vdd,
                    'id_formal': id_formal,
                    'desc_inst': 'fascicle-cross-section',
                    'diameter-um': fdum,
                }
            )

    updated_transitive = None

    objects = {obj_uuid: {'id_type': 'package', 'id_file': obj_file_id}}
    values_objects = values_objects_from_objects(objects)
    values_dataset_object = [(dataset_uuid, obj_uuid)]

    def make_values_instances(i):
        values_instances = [
            (
                d.uuid,
                f,
                inst['type'],
                i.luid[inst['desc_inst']],
                inst['id_sub'] if 'id_sub' in inst else None,
                inst['id_sam'] if 'id_sam' in inst else None,
            )
            for (d, f), inst in instances.items()
            if inst['desc_inst'] != 'nerve-cross-section'  # XXX already handled from the jp2 side
        ]
        return values_instances

    def make_values_parents(luinst):
        """need the lookup for instances"""
        values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        void = [
            (
                o,
                i.id_nerve_cross_section,
                i.addr_dFasc_um_idx,
                None,
            )  # FIXME add_const_null is wrong, should be "from curator"
            for o, b in objects.items()
            if b['id_type'] == 'package'
        ] + [
            (
                o,
                i.id_fascicle_cross_section,
                i.addr_dFasc_um_idx,
                None,
            )  # FIXME add_const_null is wrong, should be "from curator"
            for o, b in objects.items()
            if b['id_type'] == 'package'
        ]
        return void

    def make_vocd(this_dataset_updated_uuid, i):
        vocd = [(o, i.cd_obj, i.addr_const_null) for o, b in objects.items() if b['id_type'] == 'package']
        return vocd

    def make_voqd(this_dataset_updated_uuid, i):
        voqd = [
            (obj_uuid, i.qd_count, i.addr_NFasc),
            (obj_uuid, i.qd_nerve_cs_diameter_um, i.addr_dNerve_um),
            (obj_uuid, i.qd_fasc_cs_diameter_um, i.addr_dFasc_um_value),
            (obj_uuid, i.qd_nvlai1, i.addr_level),
            (obj_uuid, i.qd_nvlain1, i.addr_level),
            (obj_uuid, i.qd_nvlaix1, i.addr_level),
        ]
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        values_cv = [
            (
                None,
                i.ct_hack,
                obj_uuid,
                i.id_nerve_cross_section,
                i.cd_obj,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[dataset_uuid, id_formal],  # get us the instance
            )
            for id_formal in [e['id_formal'] for e in nerve_qvs]
        ] + [
            (
                None,
                i.ct_hack,
                obj_uuid,
                i.id_fascicle_cross_section,
                i.cd_obj,  # if we mess this up the fk ok obj_desc_cat will catch it :)
                luinst[dataset_uuid, id_formal],  # get us the instance
            )
            for id_formal in [e['id_formal'] for e in fasc_qvs]
        ]

        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        values_qv = [
            (
                e[k],
                obj_uuid,
                i.luid[e['desc_inst']],
                qd,
                luinst[dataset_uuid, e['id_formal']],
                e[k],
            )
            for e, k, qd in [
                (e, k, qd)
                for e in nerve_qvs
                for k, qd in (
                    ('number-of-fascicles', i.qd_count),  # FIXME population of thing counts within context
                    ('diameter-um', i.qd_nerve_cs_diameter_um),
                    ('vd', i.qd_nvlai1),
                    ('vd-min', i.qd_nvlain1),
                    ('vd-max', i.qd_nvlaix1),
                )
            ]
            + [
                (e, k, qd)
                for e in fasc_qvs
                for k, qd in (
                    ('diameter-um', i.qd_fasc_cs_diameter_um),
                    ('vd', i.qd_nvlai1),
                    ('vd-min', i.qd_nvlain1),
                    ('vd-max', i.qd_nvlaix1),
                )
            ]
        ]
        return values_qv

    return (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    )


def extract_template(dataset_uuid, source_local=True):

    updated_transitive = None

    instances = None
    parents = None
    objects = None

    values_objects = None
    values_dataset_object = None

    def make_values_instances(i):
        return values_instances

    def make_values_parents(luinst):
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        return void

    def make_vocd(this_dataset_updated_uuid, i):
        return vocd

    def make_voqd(this_dataset_updated_uuid, i):
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        return values_qv

    return (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    )


def ingest_demo(session, source_local=True, do_insert=True, commit=False, dev=False):
    dataset_uuid = '55c5b69c-a5b8-4881-a105-e4048af26fa5'
    ingest(dataset_uuid, extract_demo, session, commit=commit, dev=dev)


def ingest_demo_jp2(session, source_local=True, do_insert=True, commit=False, dev=False):
    dataset_uuid = '55c5b69c-a5b8-4881-a105-e4048af26fa5'
    ingest(dataset_uuid, extract_demo_jp2, session, commit=commit, dev=dev)


def ingest_reva_ft_all(session, source_local=False, do_insert=True, batch=False, commit=False, dev=False):

    dataset_uuids = (
        'aa43eda8-b29a-4c25-9840-ecbd57598afc',  # f001
        # the rest have uuid1 issues :/ all in the undefined folder it seems, might be able to fix with a reupload
        'bc4cc558-727c-4691-ae6d-498b57a10085',  # f002  # XXX has a uuid1 so breaking in prod right now have to push the new pipelines
        'ec6ad74e-7b59-409b-8fc7-a304319b6faf',  # f003  # also uuid1 issue
        'a8b2bdc7-54df-46a3-810e-83cdf33cfc3a',  # f004
        '04a5fed9-7ba6-4292-b1a6-9cab5c38895f',  # f005
    )

    batched = []
    for dataset_uuid in dataset_uuids:
        if do_insert and not batch:
            ingest(dataset_uuid, extract_reva_ft, session, source_local=source_local, commit=commit, dev=dev)
        else:
            # FIXME make it possible to stage everything and then batch the inserts
            values_args = extract_reva_ft(dataset_uuid, source_local=source_local)
            if batch:
                batched.append((dataset_uuid, values_args))

    if do_insert and batch:
        for duuid, vargs in batched:
            ingest(duuid, None, session, commit=commit, dev=dev, values_args=vargs)


def main(source_local=False, commit=False, echo=True):
    from quantdb.config import auth

    dbkwargs = {k: auth.get(f'db-{k}') for k in ('user', 'host', 'port', 'database')}  # TODO integrate with cli options
    dbkwargs['dbuser'] = dbkwargs.pop('user')
    engine = create_engine(dbUri(**dbkwargs))
    engine.echo = echo
    session = Session(engine)

    if False:
        try:
            ingest_reva_ft_all(session, source_local=source_local, do_insert=True, batch=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    if False:
        try:
            ingest_demo_jp2(session, source_local=source_local, do_insert=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    if False:
        try:
            ingest_demo(session, source_local=source_local, do_insert=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    session.close()
    engine.dispose()


if __name__ == '__main__':
    main()
