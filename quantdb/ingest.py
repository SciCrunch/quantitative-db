import sys
import pathlib
from collections import defaultdict
import requests
from pyontutils.utils_fast import isoformat
from sparcur.utils import fromJson
from sparcur import objects as sparcur_objects  # register pathmeta type

try:
    if get_ipython().__class__.__name__ == 'ZMQInteractiveShell':
        import sys  # FIXME hack that should be in jupyter-repl env or something
        sys.breakpointhook = lambda : None
except NameError:
    pass

dataset_uuid = 'aa43eda8-b29a-4c25-9840-ecbd57598afc'
resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')

blob = resp.json()

for j in blob['data']:
    j['type'] = 'pathmeta'

ir = fromJson(blob)

updated_transitive = max([i['timestamp_updated'] for i in ir['data'][1:]])  # 1: to skip the dataset object itself

jpx = [r for r in ir['data'] if 'mimetype' in r and r['mimetype'] == 'image/jpx']


"""
l left
r right
c cardiac not left or right but a branch on its own
a abdominal
p posterior

c cervical
t throacic
a abdominal
"""
sam_ordering = {
    'l': 0,  # left
    'r': 0,  # right
    'c': 0,  # cardiac safe to keep at zero since the c index usually come after t
    'a': 1,  # anterior abdominal
    'p': 1,  # posterior abdominal
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
            #print('c sample', sample)
            #rest = int(''.join(_ for _ in seg_id if _.isdigit()))
            rest = int(seg_id[:-1])
            suffix = int(seg_id[-1].encode().hex())
            return sam_ind, 0, rest, suffix
        else:
            msg = f'unknown seg {sample}'
            print(msg)  # FIXME TODO logging
            #raise ValueError(msg)
            #return int(f'{sam_ind}000')
            return sam_ind, 0, 0, 0

    rest = int(seg_id[len(prefix):])  # FIXME this convention is not always followed
    comps = sam_ind, seg_ind, rest, 0
    #return int(f'{sam_ind}{seg_ind}{rest:0>2d}')
    return comps


def pps(path_structure):
    if len(path_structure) == 6:
        # FIXME utter hack
        top, subject, sam_1, segment, modality, file = path_structure
        p1 = sam_1, subject  # child, parent to match db convention wasDerivedFrom
        p2 = segment, sam_1
        return {
            'parents': (p1, p2),
            'subject': subject,
            'sample': segment,
            'modality': modality,
            # note that because we do not convert to a single value we cannot include raw_anat_index in the qdb but that's ok
            'raw_anat_index_v1': anat_index(segment),
        }
    else:
        raise NotImplementedError(path_structure)


def ext(j):
    out = {}
    out['dataset'] = j['dataset_id']
    out['object'] = j['remote_id']
    out['file_id'] = j['file_id'] if 'file_id' in j else int(j['uri_api'].rsplit('/')[-1])  # XXX old pathmeta schema that didn't include file id
    ps = pathlib.Path(j['dataset_relative_path']).parts
    [p for p in ps if p.startswith('sub-') or p.startswith('sam-')]
    out.update(pps(ps))
    return out


exts = [ext(j) for j in jpx]
#hrm = sorted(exts, key=lambda j: j['raw_anat_index'])
#max_rai  = max([e['raw_anat_index'] for e in exts])
#import math
#log_max_rai = math.log10(max_rai)

# normalize the index by mapping distinct values to the integers
nondist = sorted([e['raw_anat_index_v1'] for e in exts])
lin_distinct = {v:i for i, v in enumerate(sorted(set([e['raw_anat_index_v1'] for e in exts])))}
max_distinct = len(lin_distinct)
mdp1 = max_distinct + 0.1  # to simplify adding overlap

dd = defaultdict(list)
for e in exts:
    #e['norm_anat_index'] = math.log10(e['raw_anat_index']) / log_max_rai
    pos = lin_distinct[e['raw_anat_index_v1']]
    e['norm_anat_index_v1'] =  (pos + 0.55) / mdp1
    e['norm_anat_index_v1_min'] =  pos / mdp1
    e['norm_anat_index_v1_max'] =  (pos + 1.1) / mdp1  # ensure there is overlap between section for purposes of testing
    # TODO norm_anat_index_min
    # TODO norm_anat_index_max
    dd[e['dataset'], e['sample']].append(e)
inst_obj_index = dict(dd)

max_nai = max([e['norm_anat_index_v1'] for e in exts])
min_nain = min([e['norm_anat_index_v1_min'] for e in exts])
max_naix = max([e['norm_anat_index_v1_max'] for e in exts])

if False:
    x = list(range(len(exts)))
    #ry = sorted([e['raw_anat_index'] for e in exts])
    ny = sorted([e['norm_anat_index_v1'] for e in exts])
    nyn = sorted([e['norm_anat_index_v1_min'] for e in exts])
    nyx = sorted([e['norm_anat_index_v1_max'] for e in exts])
    nnx = list(zip(nyn, nyx))
    import pylab as plt
    import seaborn
    #plt.figure()
    #seaborn.scatterplot(x=x, y=ry)
    plt.figure()
    #end = 10
    end = len(x)
    seaborn.scatterplot(x=x[:end], y=ny[:end])
    seaborn.scatterplot(x=x[:end], y=nyn[:end])
    seaborn.scatterplot(x=x[:end], y=nyx[:end])

# obj_desc_inst =

#values_inst_obj = [
    #for (d, f), i in instances.items()
#]

datasets = {i.uuid: {'id_type': i.type}
            for e in exts
            if (i := e['dataset'])
            }

packages = {i.uuid: {
    'id_type': i.type,
    'id_file': e['file_id'],
}
        for e in exts
            if (i := e['object'])
            }

objects = {**datasets, **packages}
dataset_object = list(set((d.uuid, o.uuid) for e in exts
                          if (d := e['dataset']) and (o := e['object'])
                          ))

subjects = {k: {'type': 'subject',
                'desc_inst': 'human'} for k in sorted(set((e['dataset'], e['subject']) for e in exts))}
segments = {k[:2]: {'type': 'sample',  # FIXME vs below ???
                    'desc_inst': 'nerve-volume',  # FIXME should this be nerve-segment and then we use nerve-volume for the 1:1 with files?
                    'id_sub': k[-1]} for k in sorted(set((e['dataset'], e['sample'], e['subject']) for e in exts))}
parents = sorted(set((e['dataset'],) + p for e in exts for p in e['parents']))
sam_other = {p[:2]:{'type': 'sample', 'desc_inst': 'nerve', 'id_sub': p[-1]} for p in parents if p[:2] not in segments}
samples = {**segments, **sam_other}
instances = {**subjects, **samples}

# this is where things get annoying with needing selects on instance measured
values_cat = {
}
values_quant = {}


from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
try:
    sigh == True  # XXX jupyter and not cleaning updb connections when binding a name over an existing name ... sigh
except NameError:
    engine = create_engine(f'postgresql+psycopg2{"cffi" if hasattr(sys, "pypy_version_info") else ""}://quantdb-user@localhost/quantdb_test')
    engine.echo = True
    session = Session(engine)
    sigh = True

list(session.execute(sql_text('select * from values_inst')))
import uuid

# from interlex.core import makeParamsValues
# XXX fix the insane brokeness of how types works here
from sqlalchemy.sql import bindparam
class getName:
    class MyBool:
        """ python is dumb """

    def __init__(self):
        self.counter = -1
        self.value_to_name = {}

    def valueCheck(self, value):
        if isinstance(value, dict):
            value = hash(frozenset((k, self.valueCheck(v)
                                    if isinstance(v, list) or isinstance(v, dict)
                                    else v)
                                    for k, v in value.items()))
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

        values_template = ', '.join('(' + ', '.join(constants +
                                                    tuple(':' + name
                                                          for name in names)) + ')'
                                    for names, _ in proto_params)
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




def address_from_fadd_type_fadd(fadd_type, fadd):
    # FIXME multi etc.
    res = [i for i, in session.execute(sql_text("select * from address_from_fadd_type_fadd(:fadd_type, :fadd)"), dict(fadd_type=fadd_type, fadd=fadd))]
    if res:
        return res[0]


def desc_inst_from_label(label):
    # FIXME multi etc.
    res = [i for i, in session.execute(sql_text("select * from desc_inst_from_label(:label)"), dict(label=label))]
    if res:
        return res[0]


def desc_quant_from_label(label):
    # FIXME multi etc.
    res = [i for i, in session.execute(sql_text("select * from desc_quant_from_label(:label)"), dict(label=label))]
    if res:
        return res[0]


def desc_cat_from_label_domain_label(label, domain_label):
    # FIXME multi etc.
    res = [i for i, in session.execute(sql_text("select * from desc_cat_from_label_domain_label(:label, :domain_label)"),
                                       dict(label=label, domain_label=domain_label))]
    if res:
        return res[0]


def cterm_from_label(label):
    # FIXME multi etc.
    res = [i for i, in session.execute(sql_text("select * from cterm_from_label(:label)"), dict(label=label))]
    if res:
        return res[0]


def insts_from_dataset_ids(dataset, ids):
    return list(session.execute(sql_text("select * from insts_from_dataset_ids(:dataset, :ids)"), dict(dataset=dataset, ids=ids)))


addr_suid = address_from_fadd_type_fadd('tabular-header', 'id_sub')
addr_said = address_from_fadd_type_fadd('tabular-header', 'id_sam')
addr_spec = address_from_fadd_type_fadd('tabular-header', 'species')
addr_saty = address_from_fadd_type_fadd('tabular-header', 'sample_type')

addr_tmod = address_from_fadd_type_fadd('tabular-header', 'modality')
#addr_trai = address_from_fadd_type_fadd('tabular-header', 'raw_anat_index')
#addr_tnai = address_from_fadd_type_fadd('tabular-header', 'norm_anat_index')
#addr_context = address_from_fadd_type_fadd('context', '#/path-metadata/{index of match remote_id}/dataset_relative_path')  # XXX this doesn't do what we want, I think what we really would want in these contexts are objects_internal that reference the file system state for a given updated snapshot, that is the real "object" that corresponds to the path-metadata.json that we are working from

#addr_jpmod = address_from_fadd_type_fadd('json-path-with-types', '#/#int/modality')
#addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/#int/anat_index')
#addr_jpnai = address_from_fadd_type_fadd('json-path-with-types', '#/#int/norm_anat_index')

addr_jpdrp = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path')

# XXX these are more accurate if opaque
addr_jpmod = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-modality')
#addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-raw-anat-index')
addr_jpnai = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1')
addr_jpnain = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-min')
addr_jpnaix = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-max')
addr_jpsuid = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-subject-id')
addr_jpsaid = address_from_fadd_type_fadd('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-sample-id')

addr_jpspec = address_from_fadd_type_fadd('json-path-with-types', '#/local/tom-made-it-up/species')
addr_jpsaty = address_from_fadd_type_fadd('json-path-with-types', '#/local/tom-made-it-up/sample_type')

# future version when we actually have the metadata files
#addr_jpmod = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/manifest/#int/modality')
#addr_jprai = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/raw_anat_index')
#addr_jpnai = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/norm_anat_index')
#addr_jpsuid = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/subjects/#int/id_sub')
#addr_jpsaid = address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/id_sam')

addr_const_null = address_from_fadd_type_fadd('constant', None)

#qd_rai = desc_quant_from_label('reva ft sample anatomical location distance index raw')
qd_nai = desc_quant_from_label('reva ft sample anatomical location distance index normalized v1')
qd_nain = desc_quant_from_label('reva ft sample anatomical location distance index normalized v1 min')
qd_naix = desc_quant_from_label('reva ft sample anatomical location distance index normalized v1 max')

cd_mod = desc_cat_from_label_domain_label('hasDataAboutItModality', None)
cd_bot = desc_cat_from_label_domain_label('bottom', None)  # we just need something we can reference that points to null so we can have a refernce to all the objects

id_human = desc_inst_from_label('human')
id_nerve = desc_inst_from_label('nerve')
id_nerve_volume = desc_inst_from_label('nerve-volume')

ct_mod = cterm_from_label('microct')  # lol ct ct

luid = {
    'human': id_human,
    'nerve': id_nerve,
    'nerve-volume': id_nerve_volume,
}
luct = {
    'microct': ct_mod,
}

res0 = session.execute(
    sql_text('INSERT INTO objects (id, id_type) VALUES (:id, :id_type) ON CONFLICT DO NOTHING'),
    dict(id=dataset_uuid, id_type='dataset'))

# oh dear https://stackoverflow.com/questions/34708509/how-to-use-returning-with-on-conflict-in-postgresql
res1 = session.execute(
    sql_text("WITH ins AS (INSERT INTO objects_internal (type, dataset, updated_transitive, label) VALUES ('path-metadata', :dataset, :updated_transitive, :label) ON CONFLICT DO NOTHING RETURNING id) SELECT id FROM ins UNION ALL SELECT id FROM objects_internal WHERE type = 'path-metadata' AND dataset = :dataset AND updated_transitive = :updated_transitive"),  # TODO see whether we actually need union all here or whether union by itself is sufficient
    dict(dataset=dataset_uuid, updated_transitive=updated_transitive, label=f'test-load-for-f001 {isoformat(updated_transitive)}'))

# it is better to use this approach for all top down information
# just assume that it is coming from some combination of the metadata files and the file system
# and leave it at that, prov can be chased down later if needed
this_dataset_updated_uuid = [i for i, in res1][0]

res1_1 = session.execute(
    sql_text('INSERT INTO objects (id, id_type, id_internal) VALUES (:id, :id_type, :id) ON CONFLICT DO NOTHING'),  # FIXME bad ocdn here
    dict(id=this_dataset_updated_uuid, id_type='quantdb'))

#fake_subjects_uuid = '9fd33009-dd23-4861-bdeb-ddeccdc6875a'
#fake_samples_uuid = 'b71e86f8-10ca-40ce-b368-710aeb696d81'
#fake_manifest_uuid = 'c5247893-31fc-4751-9953-31d799881d1d'

#res2 = session.execute(
#    sql_text("INSERT INTO objects (id_type, id, id_file) VALUES ('package', :suid, 0), ('package', :said, 0), ('package', :maid, 0) ON CONFLICT DO NOTHING"),
#    dict(suid=fake_subjects_uuid, said=fake_samples_uuid, maid=fake_manifest_uuid))

values_objects = [
    (i, o['id_type'], o['id_file'] if 'id_file' in o else None)
    for i, o in objects.items()
    if o['id_type'] != 'dataset'  # already did it above
]
values_dataset_object = dataset_object
values_instances = [
    (d.uuid, f, i['type'], luid[i['desc_inst']],
     i['id_sub'] if 'id_sub' in i else None,
     i['id_sam'] if 'id_sam' in i else None,
     )
    for (d, f), i in instances.items()]

dev = False
ocdn = ' ON CONFLICT DO NOTHING' if dev else ''
vt, params = makeParamsValues(values_objects)
session.execute(sql_text(f'INSERT INTO objects (id, id_type, id_file) VALUES {vt}{ocdn}'), params)

vt, params = makeParamsValues(values_dataset_object)
session.execute(sql_text(f'INSERT INTO dataset_object (dataset, object) VALUES {vt}{ocdn}'), params)

vt, params = makeParamsValues(values_instances)
session.execute(sql_text(f'INSERT INTO values_inst (dataset, id_formal, type, desc_inst, id_sub, id_sam) VALUES {vt}{ocdn}'), params)

ilt = insts_from_dataset_ids(dataset_uuid, [f for d, f in instances])
luim = {(str(dataset), id_formal): id for id, dataset, id_formal in ilt}

values_parents = [
    (luim[d.uuid, child], luim[d.uuid, parent])
    for d, child, parent in parents]

vt, params = makeParamsValues(values_parents)
session.execute(sql_text(f'INSERT INTO instance_parent VALUES {vt}{ocdn}'), params)

void = [  # FIXME this is rather annoying because you have to list all expected types in advance, but I guess that is what we want

    (this_dataset_updated_uuid, id_human, addr_jpsuid, addr_jpspec),
    (this_dataset_updated_uuid, id_nerve, addr_jpsaid, addr_jpsaty),
    (this_dataset_updated_uuid, id_nerve_volume, addr_jpsaid, addr_jpsaty),

    #(fake_subjects_uuid, id_human, addr_suid, addr_spec),  # we're going to pretend that these came from subjects and samples sheets?
    #(fake_samples_uuid, id_nerve, addr_said, addr_saty),
    #(fake_samples_uuid, id_nerve_volume, addr_said, addr_saty),

    # FIXME what about manifests? those link metadata as an extra hop ... everything meta related needs to come from combined object metadata ???
    # that would certainly make more sense than the nonsense that is going on here, it would simplify the referencing for all the topdown
    # information that we have but it sort of obscures sources, however this _is_ contextual info ... sigh
    # XXX the other option would just be to just put the darned files in the instance measured table :/ because we do have data about them
    # annoying :/

#+ [(i, 'nerve-volume', addr_context) for i in packages]
] + [(o, id_nerve_volume, addr_const_null, None)  # XXX FIXME this is the only way I can think to do this right now ?
     for o, b in objects.items() if b['id_type'] == 'package']

# XXX REMINDER an object descriptor pair can be associated with an arbitrary number of measured instances
# BUT that mapping only appears when there is _something_ in the qv or cv tables so we need an object
# desc_inst pair, and an object cat or quant desc pair otherwise our constraints are violated
# when there is only a single (or zero) records per object then we just create one so that the association
# to a an instance can proceed, even if the mapping of that instance is from an external source
# XXX the external source is part of the issue I think


vt, params = makeParamsValues(void)
session.execute(sql_text(f'INSERT INTO obj_desc_inst (object, desc_inst, addr_field, addr_desc_inst) VALUES {vt}{ocdn}'), params)

vocd = [
    #(this_load_uuid, cd_mod, addr_jpmod), # pretty sure this is just wrong
    # FIXME this reveals that there are cases where we may not have void for a single file or that the id comes from context and is not embedded
    # figuring out how to turn that around is going to take a bit of thinking
    #(i, ) for i in packages
    (this_dataset_updated_uuid, cd_mod, addr_jpmod),  # FIXME also not quite right because it is really a virtual manifest composed of many manifests ... but whatever for now
] + [(o, cd_bot, addr_const_null)  # XXX FIXME this is the only way I can think to do this right now ?
     for o, b in objects.items() if b['id_type'] == 'package']

vt, params = makeParamsValues(vocd)
session.execute(sql_text(f'INSERT INTO obj_descriptors_cat (object, desc_cat, addr_field) VALUES {vt}{ocdn}'), params)

voqd = [  # FIXME this isn't quite right, we should just do it to the segments and pretend it is from the samples file I think?
    #(fake_samples_uuid, qd_rai, addr_trai),
    #(fake_samples_uuid, qd_nai, addr_tnai),
    #(this_dataset_updated_uuid, qd_rai, addr_jprai),
    (this_dataset_updated_uuid, qd_nai, addr_jpnai),
    (this_dataset_updated_uuid, qd_nain, addr_jpnain),  # XXX FIXME is this really an aggregation type in this case? I guess it technically if the sample space is over all the points inside the segment or something
    (this_dataset_updated_uuid, qd_naix, addr_jpnaix),
]

vt, params = makeParamsValues(voqd)
session.execute(sql_text(f'INSERT INTO obj_desc_quant (object, desc_quant, addr_field) VALUES {vt}{ocdn}'), params)

#obj_index = {e['object']: e for e in exts}
values_cv = [
    # value_open, value_controlled, object, desc_inst, desc_cat
    (e[k],
     luct[e[k]],
     this_dataset_updated_uuid,
     #e['object'].uuid,  # FIXME still not right this comes from the updated latest
     id_nerve_volume,
     cd,  # if we mess this up the fk ok obj_descriptors_cat will catch it :)
     luim[e['dataset'].uuid, e['sample']],  # get us the instance
     )
    for e in exts
    for k, cd in (
            ('modality', cd_mod),
    )

] + [
    ('nothing to see here',
     None,
     e['object'].uuid,
     id_nerve_volume,
     cd_bot,  # if we mess this up the fk ok obj_descriptors_cat will catch it :)
     luim[e['dataset'].uuid, e['sample']],  # get us the instance
     )
    for e in exts
]

vt, params = makeParamsValues(values_cv)
session.execute(sql_text(f'INSERT INTO values_cat (value_open, value_controlled, object, desc_inst, desc_cat, instance) VALUES {vt}{ocdn}'), params)

values_qv = [
    # value, object, desc_inst, desc_quant, inst, value_blob
    (e[k],
     #e['object'].uuid,  # FIXME TODO we could fill this here but we choose to use this_dataset_updated_uuid instead I think
     this_dataset_updated_uuid,
     id_nerve_volume,
     qd,  # if we mess this up the fk ok obj_descriptors_cat will catch it :)
     luim[e['dataset'].uuid, e['sample']],  # get us the instance
     e[k],
     )
    for e in exts
    for k, qd in (
            #('raw_anat_index', qd_rai),  # XXX this is a bad place to store object -> field -> qd mappings also risks mismatch on address
            ('norm_anat_index_v1', qd_nai),
            ('norm_anat_index_v1_min', qd_nain),
            ('norm_anat_index_v1_max', qd_naix),
    )
]

vt, params, bindparams = makeParamsValues(
    # FIXME LOL the types spec here is atrocious ... but it does work ...
    # XXX and barring the unfortunate case, which we have now encountered  where
    # now fixed in the local impl
    values_qv, row_types=(None, None, None, None, None, JSONB))

t = sql_text(f'INSERT INTO values_quant (value, object, desc_inst, desc_quant, instance, value_blob) VALUES {vt}{ocdn}')
tin = t.bindparams(*bindparams)
session.execute(tin, params)

if False:
    session.commit()
    session.close()
    engine.dispose()

# this is a bit confusing because the thing we are extracting from is actually
# an "internal" object which is path-metadata.json for a whole dataset at a timepoint
# the newer version will have the updated timestamp which can make this easier
# but we can use resp.headers['Last-Modified'] if needed
#('INSERT INTO addresses (addr_type, addr_field, value_type) VALUES ')
#(
    #('json-path-with-types', '#/data/#int/dataset_relative_path', 'multi')  # we derive pretty much everything from dataset relative path
    #('json-path-with-types', '#/#int/')  # we aren't really pulling from path-metadata.json directly, this is some derive structure
#)
#list(session.execute(sql_text("select * from address_from_fadd_type_fadd('json-path-with-types', '#/data/#int/dataset_relative_path')")))


#vt, params = makeParamsValues()

f'INSERT INTO objects (id, id_type) VALUES {vt}'
f'INSERT INTO objects (id, id_type, id_file) VALUES {vt}'

'INSERT INTO values_inst VALUES'
'INSERT INTO parents_inst VALUES'

'INSERT INTO obj_desc_inst VALUES'
'INSERT INTO obj_desc_quant VALUES'
'INSERT INTO obj_descriptors_cat VALUES'

'INSERT INTO values_quant VALUES'
'INSERT INTO values_cat VALUES'

if False:
    ps = top, subject, sam_1, sam_2, modality, file = pathlib.Path(jpx[0]['dataset_relative_path']).parts

    dd = defaultdict(list)
    for o in hrm:
        dd[o['sample']].append(o)
    by_sam = dict(dd)