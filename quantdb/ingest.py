import json
import pathlib
import sys
from collections import defaultdict, Counter

import requests
from pyontutils.utils_fast import chunk_list
from sparcur import objects as sparcur_objects  # register pathmeta type
from sparcur.paths import Path
from sparcur.utils import PennsieveId as RemoteId
from sparcur.utils import fromJson, log as _slog, register_type
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import bindparam
from sqlalchemy.sql import text as sql_text

from quantdb.utils import dbUri, isoformat, log

# good trick for truncating insane errors messages
#import sys
#
#class DevNull:
#    def write(self, msg):
#        pass
#
#sys.stderr = DevNull()

# from pyontutils.identity_bnode
def toposort(adj, unmarked_key=None):
    # XXX NOTE adj cannot be a generator
    _dd = defaultdict(list)
    [_dd[a].append(b) for a, b in adj]
    nexts = dict(_dd)

    _keys = set([a for a, b in adj])
    _values = set([b for a, b in adj])
    starts = list(_keys - _values)

    unmarked = sorted((_keys | _values), key=unmarked_key)
    temp = set()
    out = []
    def visit(n):
        if n not in unmarked:
            return
        if n in temp:
            import pprint
            raise Exception(f'oops you have a cycle {n}\n{pprint.pformat(n)}', n)

        temp.add(n)
        if n in nexts:
            for m in nexts[n]:
                visit(m)

        temp.remove(n)
        unmarked.remove(n)
        out.append(n)

    while unmarked:
        n = unmarked[0]
        visit(n)

    return out


# from interlex.ingest
def subst_toposort(edges, unmarked_key=None):
    # flip acts as last one wins so there is still only ever a single
    # integer id for each node, we just use the last occurance
    genind = iter(range(len(edges * 2)))
    flip = {e: next(genind) for so in edges for e in so}
    flop = {v: k for k, v in flip.items()}
    fedges = [tuple(flip[e] for e in edge) for edge in edges]
    if unmarked_key is not None:
        def unmarked_key(k, _unmarked_key=unmarked_key):
            return _unmarked_key(flop[k])

    fsord = toposort(fedges, unmarked_key=unmarked_key)
    sord = [flop[s] for s in fsord]
    return sord


def skey(abc):
    a, b, c = abc
    if b.startswith('sub-'):  # pop case maybe?
        return 0
    elif b.startswith('sam-'):
        if c.startswith('sub-'):
            return 1
        elif c.startswith('sam-'):
            return 2
        else:
            raise ValueError(f'wat {abc}')
    elif b.startswith('site-'):
        return 3
    elif b.startswith('fasc-'):
        return 4
    elif b.startswith('fiber-'):
        return 5
    else:
        return 9999


def sort_parents(parents):
    # the only bit that needs to be toposorted after this
    # is the samples, which should be a much smaller set
    s_parents = sorted(parents, key=skey)
    b_sam = None
    e_sam = None
    for i, (a, b, c) in enumerate(s_parents):
        if b_sam is None and b.startswith('sam-') and c.startswith('sam-'):
            b_sam = i

        if b_sam is not None and e_sam is None and not b.startswith('sam-'):
            e_sam = i
            break

    if b_sam is None:
        parents = s_parents
    else:
        pre_sasa_parents = s_parents[:b_sam]
        sasa_parents = s_parents[b_sam:] if e_sam is None else s_parents[b_sam:e_sam]
        post_sasa_parents = [] if e_sam is None else s_parents[e_sam:]
        sord = subst_toposort([((a, b), (a, c)) for a, b, c in sasa_parents])
        def ssord(abc):
            a, b, c = abc
            return sord.index((a, b)), sord.index((a, c))

        ts_sasa = sorted(sasa_parents, key=ssord)
        parents = pre_sasa_parents + ts_sasa + post_sasa_parents

    return parents


# FIXME sparcur dependencies, or keep ingest separate

######### start database interaction section

log.removeHandler(log.handlers[0])
log.addHandler(_slog.handlers[0])

log = log.getChild('ingest')


try:
    if get_ipython().__class__.__name__ == 'ZMQInteractiveShell':
        import sys  # FIXME hack that should be in jupyter-repl env or something

        sys.breakpointhook = lambda: None
except NameError:
    pass


def check_parents_instances(instances, parents):
    # also transitive check needed
    parents_direct_ss = set(
        (s, r[k]) for (d, s), r in instances.items()
        for k in ('id_sub', 'id_sam')
        if k in r and s != r[k])
    parents_direct = set((c, p) for d, c, p in parents)
    diff = parents_direct_ss - parents_direct
    starts = set(a for a, b in parents_direct)
    starts_ss = set(a for a, b in parents_direct_ss)
    mis_starts = (starts_ss - starts) | (starts - starts_ss)
    ends = set(b for a, b in parents_direct)
    ends_ss = set(b for a, b in parents_direct_ss)
    me_a, me_b = (ends_ss - ends), (ends - ends_ss)
    # all coming from me_b so ones that are missing in subject or sample because they are
    # either not a subject or sample, or are metadata only i think?
    # so in essence parents does have everything ... but there still should be a connection down
    mis_ends = me_a | me_b
    debug = True
    if debug:
        c, p = 'fasc-site-l-seg-c1-B-L3-3-th-1', 'site-l-seg-c1-B-L3-3-th'
        ip = 'sam-l-seg-c1-B-L3'
        iip = 'sam-l-seg-c1-B'
        iiip = 'sam-l-seg-c1'
        iiiip = 'sam-l'
        _1 = [(a, b) for a, b in parents_direct if a == c]
        _2 = [(a, b) for a, b in parents_direct_ss if a == c]
        _3 = [(a, b) for a, b in parents_direct if a == p]
        _4 = [(a, b) for a, b in parents_direct_ss if a == p]
        _5 = [(a, b) for a, b in parents_direct if a == ip]
        _6 = [(a, b) for a, b in parents_direct_ss if a == ip]
        _7 = [(a, b) for a, b in parents_direct if a == iip]
        _8 = [(a, b) for a, b in parents_direct_ss if a == iip]
        _9 = [(a, b) for a, b in parents_direct if a == iiip]
        _10 = [(a, b) for a, b in parents_direct_ss if a == iiip]
        _11 = [(a, b) for a, b in parents_direct if a == iiiip]
        _12 = [(a, b) for a, b in parents_direct_ss if a == iiiip]
        _sigh = (_1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11, _12)
        pp = [a for i, a in enumerate(_sigh) if i % 2 == 0]
        ss = [a for i, a in enumerate(_sigh) if i % 2 != 0]
    breakpoint()
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

    if sample.count('-') < 3:
        sam, sam_id = sample.split('-')
        seg_id = None
    else:
        sam, sam_id, seg, seg_id, *_rest = sample.split('-')
        if _rest:
            log.debug(_rest)

    # FIXME bad becase left and right are unstable and we don't care about this, we just want relative to max possible
    # don't do this with sort
    sam_ind = sam_ordering[sam_id]
    if seg_id is None:
        return sam_ind, 0, 0, 0

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
            log.debug(msg)
            # raise ValueError(msg)
            # return int(f'{sam_ind}000')
            return sam_ind, 0, 0, 0

    rest = int(seg_id[len(prefix) :])  # FIXME this convention is not always followed
    comps = sam_ind, seg_ind, rest, 0
    # return int(f'{sam_ind}{seg_ind}{rest:0>2d}')
    return comps


def proc_anat(rawind):
    # normalize the index by mapping distinct values to the integers
    lin_distinct = {v: i for i, v in enumerate(sorted(set(rawind.values())))}
    max_distinct = len(lin_distinct)
    mdp1 = max_distinct + 0.1  # to simplify adding overlap
    sindex = {}
    for (d, s), raw in rawind.items():
        # e['norm_anat_index'] = math.log10(e['raw_anat_index']) / log_max_rai
        pos = lin_distinct[raw]
        inst = (pos + 0.55) / mdp1
        minp = pos / mdp1
        maxp = (pos + 1.1) / mdp1  # ensure there is overlap between section for purposes of testing
        sindex[(d, s)] = inst, minp, maxp

    return sindex


_translate_species = {}
_translate_species['ncbitaxon:9606'] = 'human'  # oof
def translate_species(v):
    return _translate_species[v]


_translate_sample_type = {
    # FIXME not generally true needs scope or rather a per dataset/schema way
    'nerve': 'nerve',
    'segment': 'nerve-volume',
    'subsegment': 'nerve-volume',
    'section': 'nerve-cross-section',
}
def translate_sample_type(v):
    return _translate_sample_type[v]


_translate_site_type = {}
_translate_site_type['extruded plane'] = 'extruded-plane'
def translate_site_type(v):
    return _translate_site_type[v]


def pps(path_structure, dataset_metadata=None):
    level = None
    site = None
    site_type = None
    fasc = None
    if len(path_structure) == 6:
        # FIXME utter hack
        top, subject, sam_1, segment, modality, file = path_structure
        sample_type = 'nerve-cross-section'  # FIXME or is it volume
        if segment.startswith('site-'):
            site = segment
            site_meta = [s for s in dataset_metadata['sites'] if s['site_id'] == site][0]
            site_type = translate_site_type(site_meta['site_type'])
            if dataset_metadata is not None:
                # not actually segment, usually level
                segment = site_meta['specimen_id']
            else:
                segment = None

        if modality.startswith('fasc-'):
            # FIXME we may want to skip in this case because they are aggregated later in the higher level fibers.csv files
            fasc = modality
    elif len(path_structure) == 5:
        top, subject, sam_1, segment, file = path_structure
        if segment.startswith('site-'):
            site = segment
            site_meta = [s for s in dataset_metadata['sites'] if s['site_id'] == site][0]
            site_type = translate_site_type(site_meta['site_type'])
            if dataset_metadata is not None:
                # not actually segment, usually level
                segment = site_meta['specimen_id']
            else:
                segment = None  # FIXME without sites metadata we can't determine the actual sample so have to backfill later

        if segment is not None and segment.count('-') > 3:
            level = segment

        modality = None  # FIXME from metadata sample id
        if file.endswith('.jpx') and ('9um' in file or '36um' in file):
            modality = 'microct'
            sample_type = 'nerve-volume'
        elif file.endswith('fascicles.csv') or file.endswith('fibers.csv'):
            # XXX watch out for the fact that fibers files are present at multiple levels
            modality = 'ihc'
            sample_type = 'nerve-cross-section'
        else:
            raise NotImplementedError(path_structure)
    else:
        raise NotImplementedError(path_structure)

    # XXX folder structure CANNOT be used to infer direct parent structure
    #p1 = sam_1, subject  # child, parent to match db convention wasDerivedFrom
    #p2 = segment, sam_1
    #if level is None:
    #    parents = (p1, p2)
    #else:
    #    parents = (p1,)  # get it from metadata
    parents = tuple()

    return {
        'parents': parents,
        'subject': subject,
        'sample': segment,
        'sample_type': sample_type,
        'site': site,
        'site_type': site_type,
        'fasc': fasc,
        'modality': modality,
        # note that because we do not convert to a single value we cannot include raw_anat_index in the qdb but that's ok
        'raw_anat_index_v2': None if segment is None else anat_index(segment),  # FIXME deal with sites on this too ...
    }


def pps123(path_structure, dataset_metadata=None):
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
        'sample_type': 'nerve-cross-section',
        'site': None,
        'site_type': None,
    }


def ext_pmeta(j, dataset_metadata=None, _pps=pps):
    out = {}
    out['dataset'] = j['dataset_id']
    out['object'] = j['remote_id']
    out['file_id'] = (
        j['file_id'] if 'file_id' in j else int(j['uri_api'].rsplit('/')[-1])
    )  # XXX old pathmeta schema that didn't include file id
    ps = pathlib.Path(j['dataset_relative_path']).parts
    [p for p in ps if p.startswith('sub-') or p.startswith('sam-')]
    out.update(_pps(ps, dataset_metadata))
    return out


def ext_pmeta123(j):
    return ext_pmeta(j, _pps=pps123)


class Queries:
    def __init__(self, session):
        self.session = session
        self._inv = {}

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
                self._inv['addr', out] = params
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
                self._inv['id', out] = params
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
                #kp = 'qdfi' if 'fiber' in label else 'qd'  # FIXME sigh XXX actually wasn't the issue i think?
                #k = kp, out
                self._inv['qd', out] = params
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
                self._inv['cd', out] = params
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
                self._inv['ct', out] = params
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

    def reg_qd(self, qd_label):
        if qd_label not in self._qdmap:
            qd = self._q.desc_quant_from_label(qd_label)
            if qd is None:
                raise KeyError(qd_label)

            self._qdmap[qd_label] =  qd

        return self._qdmap[qd_label]

    def reg_addr(self, addr_label, addr_type='tabular-header'):
        if addr_label not in self._addrmap:
            addr = self._q.address_from_fadd_type_fadd(addr_type, addr_label)
            if addr is None:
                raise KeyError(addr_label)

            self._addrmap[addr_label] = addr

        return self._addrmap[addr_label]

    def __init__(self, queries):
        self._qdmap = {}
        self._addrmap = {}
        q = queries
        self._q = queries

        self.addr_index = q.address_from_fadd_type_fadd('record-index', None)
        self.addr_suid = q.address_from_fadd_type_fadd('tabular-header', 'id_sub')
        self.addr_said = q.address_from_fadd_type_fadd('tabular-header', 'id_sam')
        self.addr_spec = q.address_from_fadd_type_fadd('tabular-header', 'species')
        self.addr_saty = q.address_from_fadd_type_fadd('tabular-header', 'sample_type')

        self.addr_tmod = q.address_from_fadd_type_fadd('tabular-header', 'modality')

        self.addr_area = q.address_from_fadd_type_fadd('tabular-header', 'area')
        self.addr_fiber_area = q.address_from_fadd_type_fadd('tabular-header', 'fiber_area')
        self.addr_long_diam = q.address_from_fadd_type_fadd('tabular-header', 'longest_diameter')
        self.addr_short_diam = q.address_from_fadd_type_fadd('tabular-header', 'shortest_diameter')
        self.addr_eff_diam = q.address_from_fadd_type_fadd('tabular-header', 'eff_diam')
        self.addr_fascicle = q.address_from_fadd_type_fadd('tabular-header', 'fascicle')

        self.addr_eff_fib_diam = q.address_from_fadd_type_fadd('tabular-header', 'eff_fib_diam')
        self.addr_myelinated = q.address_from_fadd_type_fadd('tabular-header', 'myelinated')

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

        self.addr_jp_dm_sub_id = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/subjects/#int/subject_id')
        self.addr_jp_dm_sub_ty = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/subjects/#int/species#translate_species')
        self.addr_jp_dm_sam_id = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/sample_id')
        self.addr_jp_dm_sam_ty = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/samples/#int/sample_type#translate_sample_type')
        self.addr_jp_dm_site_id = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/sites/#int/site_id')
        self.addr_jp_dm_site_ty = q.address_from_fadd_type_fadd('json-path-with-types', '#/curation-export/sites/#int/sites_type#translate_sites_type')

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
        self.qd_fasc_cs_diameter_um_min = q.desc_quant_from_label('fascicle cross section diameter um min')
        self.qd_fasc_cs_diameter_um_max = q.desc_quant_from_label('fascicle cross section diameter um max')

        self.qd_fasc_cs_area_um2 = q.desc_quant_from_label('fascicle cross section area um2')

        self.qd_fiber_cs_area_um2 = q.desc_quant_from_label('fiber cross section area um2')
        self.qd_fiber_cs_diameter_um = q.desc_quant_from_label('fiber cross section diameter um')
        self.qd_fiber_cs_diameter_um_min = q.desc_quant_from_label('fiber cross section diameter um min')
        self.qd_fiber_cs_diameter_um_max = q.desc_quant_from_label('fiber cross section diameter um max')

        self.cd_axon = q.desc_cat_from_label_domain_label('hasAxonFiberType', None)
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
        self.id_fiber_cross_section = q.desc_inst_from_label('fiber-cross-section')
        self.id_myelin_cross_section = q.desc_inst_from_label('myelin-cross-section')
        self.id_extruded_plane = q.desc_inst_from_label('extruded-plane')
        self.luid = {
            'human': self.id_human,
            'nerve': self.id_nerve,
            'nerve-volume': self.id_nerve_volume,
            'nerve-cross-section': self.id_nerve_cross_section,
            'fascicle-cross-section': self.id_fascicle_cross_section,
            'fiber-cross-section': self.id_fiber_cross_section,
            'extruded-plane': self.id_extruded_plane,
        }

        self.ct_mod = q.cterm_from_label('microct')  # lol ct ct
        self.ct_hack = q.cterm_from_label('hack-associate-some-value')
        self.ct_myelinated = q.cterm_from_label('myelinated')
        self.ct_unmyelinated = q.cterm_from_label('unmyelinated')
        self.luct = {
            'ct-hack': self.ct_hack,
            'microct': self.ct_mod,
            'myelinated': self.ct_myelinated,
            'unmyelinated': self.ct_unmyelinated,
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

    batchsize = 20000
    for chunk in chunk_list(values_objects, batchsize):
        vt, params = makeParamsValues(chunk)
        session.execute(sql_text(f'INSERT INTO objects (id, id_type, id_file) VALUES {vt}{ocdn}'), params)
        if commit:
            session.commit()

    for chunk in chunk_list(values_dataset_object, batchsize):
        vt, params = makeParamsValues(chunk)
        session.execute(sql_text(f'INSERT INTO dataset_object (dataset, object) VALUES {vt}{ocdn}'), params)
        if commit:
            session.commit()

    for chunk in chunk_list(values_instances, batchsize):
        vt, params = makeParamsValues(chunk)
        session.execute(
            sql_text(f'INSERT INTO values_inst (dataset, id_formal, type, desc_inst, id_sub, id_sam) VALUES {vt}{ocdn}'),
            params,
        )
        if commit:
            session.commit()

    # inserts that depend on instances having already been inserted
    # ilt = q.insts_from_dataset_ids(dataset_uuid, [f for d, f, *rest in values_instances])
    # get all instances in a dataset since values_inst only includes instances we plan to insert
    # not those that were already inserted that we want to add values for
    ilt = q.insts_from_dataset(dataset_uuid)
    luinst = {(str(dataset), id_formal): id for id, dataset, id_formal in ilt}
    values_parents = make_values_parents(luinst)
    values_cv = make_values_cat(this_dataset_updated_uuid, i, luinst)
    values_qv = make_values_quant(this_dataset_updated_uuid, i, luinst)

    if values_parents:
        for chunk in chunk_list(values_parents, batchsize):
            vt, params = makeParamsValues(chunk)
            session.execute(sql_text(f'INSERT INTO instance_parent VALUES {vt}{ocdn}'), params)
            if commit:
                session.commit()
    else:
        # this is ok if some other ingest provides these
        log.warning(f'no parents for {dataset_uuid}')

    for chunk in chunk_list(void, batchsize):
        vt, params = makeParamsValues(chunk)
        session.execute(
            sql_text(f'INSERT INTO obj_desc_inst (object, desc_inst, addr_field, addr_desc_inst) VALUES {vt}{ocdn}'), params
        )
        if commit:
            session.commit()

    if vocd:
        for chunk in chunk_list(vocd, batchsize):
            vt, params = makeParamsValues(chunk)
            session.execute(sql_text(f'INSERT INTO obj_desc_cat (object, desc_cat, addr_field) VALUES {vt}{ocdn}'), params)
            if commit:
                session.commit()

    if voqd:
        for chunk in chunk_list(voqd, batchsize):
            vt, params = makeParamsValues(chunk)
            session.execute(
                sql_text(f'INSERT INTO obj_desc_quant (object, desc_quant, addr_field) VALUES {vt}{ocdn}'), params
            )
            if commit:
                session.commit()

    if values_cv:
        for chunk in chunk_list(values_cv, batchsize):
            vt, params = makeParamsValues(chunk)
            session.execute(
                sql_text(
                    f'INSERT INTO values_cat (value_open, value_controlled, object, desc_inst, desc_cat, instance) VALUES {vt}{ocdn}'
                ),
                params,
            )
            if commit:
                session.commit()

    if values_qv:
        for chunk in chunk_list(values_qv, batchsize):
            vt, params, bindparams = makeParamsValues(
                # FIXME LOL the types spec here is atrocious ... but it does work ...
                # XXX and barring the unfortunate case, which we have now encountered  where
                # now fixed in the local impl
                chunk,
                row_types=(None, None, None, None, None, JSONB),
            )

            t = sql_text(
                f'INSERT INTO values_quant (value, object, desc_inst, desc_quant, instance, value_blob) VALUES {vt}{ocdn}'
            )
            tin = t.bindparams(*bindparams)
            session.execute(tin, params)
            if commit:
                session.commit()


def extract_reva_ft(dataset_uuid, source_local=False, visualize=False):
    if source_local:
        with open(
            pathlib.Path(
                f'~/.local/share/sparcur/export/datasets/{dataset_uuid}/LATEST/path-metadata.json'
            ).expanduser(),
            'rt',
        ) as f:
            blob = json.load(f)

        with open(
            pathlib.Path(
                f'~/.local/share/sparcur/export/datasets/{dataset_uuid}/LATEST/curation-export.json'
            ).expanduser(),
            'rt',
        ) as f:
            blob_dataset = json.load(f)
    else:

        resp_dataset = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/curation-export.json')
        blob_dataset = resp_dataset.json()

        resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')

        try:
            blob = resp.json()
        except Exception as e:
            breakpoint()
            raise e

    ir_dataset = fromJson(blob_dataset)

    for j in blob['data']:
        j['type'] = 'pathmeta'

    ir = fromJson(blob)

    updated_transitive = max([i['timestamp_updated'] for i in ir['data'][1:]])  # 1: to skip the dataset object itself

    jpx = [r for r in ir['data'] if 'mimetype' in r and r['mimetype'] == 'image/jpx']

    exts = [ext_pmeta(j) for j in jpx]

    (instances, _parents, objects, values_objects, values_dataset_object, _, _, #values_q, values_c
     ) = ext_values(exts, dataset_metadata=ir_dataset)
    parents = _parents  # yes this is empty

    # hrm = sorted(exts, key=lambda j: j['raw_anat_index'])
    # max_rai  = max([e['raw_anat_index'] for e in exts])
    # import math
    # log_max_rai = math.log10(max_rai)

    ''' # old see proc_anat
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

    # ok if parents is empty now because fasc_fib inserts them all already
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
        if o['id_type'] != 'dataset'
    ]  # already did it above
    values_dataset_object = dataset_object
    #'''

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
            (this_dataset_updated_uuid, i.id_human, i.addr_jp_dm_sub_id, i.addr_jp_dm_sub_ty),
            (this_dataset_updated_uuid, i.id_nerve, i.addr_jp_dm_sam_id, i.addr_jp_dm_sam_ty),
            (this_dataset_updated_uuid, i.id_nerve_volume, i.addr_jp_dm_sam_id, i.addr_jp_dm_sam_ty),
            (this_dataset_updated_uuid, i.id_nerve_cross_section, i.addr_jp_dm_sam_id, i.addr_jp_dm_sam_ty),
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
            (o, i.cd_obj, i.addr_const_null)
            for o, b in objects.items()
            if b['id_type'] == 'package'  # XXX FIXME this is the only way I can think to do this right now ?
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
        srs = {k:v  for k, v in instances.items() if v['type'] == 'sample'}
        rawind = {(d, s): anat_index(s) for (d, s), v in srs.items()}
        sindex = proc_anat(rawind)
        values_qv = [
            # value, object, desc_inst, desc_quant, inst, value_blob
            (v,
             this_dataset_updated_uuid,
             i.luid[srs[(d, s)]['desc_inst']],
             qd,
             luinst[d.uuid, s],
             v,)
            for (d, s), (inst, minp, maxp) in sindex.items()
            for v, qd in ((inst, i.qd_nai), (minp, i.qd_nain), (maxp, i.qd_naix))
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
        if o['id_type'] != 'dataset'
    ]  # already did it above


def ext_values(exts, ext_contents=None, dataset_metadata=None, process_record=None, tabular_header=True):
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

    luty = {e['sample']: e['sample_type'] for e in exts}
    samples = {
        k[:2]: {
            'type': 'sample',
            'desc_inst': luty[k[1]],
            'id_sub': k[-1],
            'id_sam': k[1],
        }
        for k in sorted(set((e['dataset'], e['sample'], e['subject']) for e in exts))
    }

    lutysi = {e['site']: e['site_type'] for e in exts if e['site'] is not None}
    sites = {
        k[:2]: {
            'type': 'site',
            'desc_inst': lutysi[k[1]],  # TODO should be filled from site meta probably?
            'id_sub': k[-1],
            'id_sam': k[-2],  # TODO backfill
        }
        for k in sorted(set((e['dataset'], e['site'], e['sample'], e['subject']) for e in exts if e['site'] is not None))
    }

    if dataset_metadata:
        # add metadata only
        asdf = ((subjects, 'subjects', 'subject_id'),
                (samples, 'samples', 'sample_id'),
                (sites, 'sites', 'site_id'),)
        dm = dataset_metadata
        did = RemoteId(dm['id'])
        sample_subject = {s['sample_id']: s['subject_id'] for s in dm['samples']}  # FIXME XXX bad assumption for multi-parent
        site_subject = {s['site_id']: (s['specimen_id'] if s['specimen_id'].startswith('sub-') else sample_subject[s['specimen_id']])
                        for s in dm['sites']}
        for d, k, ik in asdf:
            if k in dataset_metadata:
                m = dataset_metadata[k]
                for rec in m:
                    thing_id = rec[ik]
                    if (did, thing_id) not in d:
                        # XXX most of these are because derivative data and primary data are not perfectly aligned
                        # or because the sample is higher up the derivation tree
                        msg = f'{rec[ik]} was not found in paths for the file type you are looking at'
                        log.debug(msg)
                        thing_type = k[:-1]
                        nr = {
                            'type': thing_type,
                        }
                        if k == 'subjects':
                            nr['desc_inst'] = translate_species(rec['species'])  # FIXME TODO translate
                            nr['id_sub'] = thing_id
                        elif k == 'samples':
                            nr['desc_inst'] = translate_sample_type(rec['sample_type'])  # FIXME TODO translate
                            nr['id_sub'] = sample_subject[thing_id]
                            nr['id_sam'] = thing_id
                        elif k == 'sites':
                            nr['desc_inst'] = translate_site_type(rec['site_type'])  # FIXME TODO translate
                            nr['id_sub'] = site_subject[thing_id]
                            spec_id = rec['specimen_id']
                            if spec_id.startswith('sam-'):
                                nr['id_sam'] = spec_id

                        d[did, thing_id] = nr

    if ext_contents:
        values_q = []
        values_c = []
        formals = set()
        bads = set()
        def add_formal(f):
            if f in formals:
                bads.add(f)

            formals.add(f)

        def add_parent(pr):
            parents.append(pr)

        def add_values(vsq, vsc):
            values_q.extend(vsq)
            values_c.extend(vsc)

        below = {
            (e['dataset'], id_formal): result
            for e in exts
            for i, record in enumerate(ext_contents[e['object']])
            if not tabular_header and i >= 0 or i >= 1
            for id_formal, result, parent_rec, vsq, vsc in process_record(e, i, record, (ext_contents[e['object']][0]) if tabular_header else None)
            if not add_formal(id_formal) and not add_parent(parent_rec) and not add_values(vsq, vsc)
        }

        if bads:
            if len(bads) > 10:
                msg = f'there are {len(bads)} duplicate formal ids'
            else:
                msg = f'duplicate formal ids {bads}'

            raise ValueError(msg)
    else:
        values_q = []
        values_c = []
        below = {}

    instances = {**subjects, **samples, **sites, **below}

    values_objects = values_objects_from_objects(objects)
    values_dataset_object = dataset_object

    return instances, parents, objects, values_objects, values_dataset_object, values_q, values_c


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

    instances, parents, objects, values_objects, values_dataset_object, _, _ = ext_values(exts)

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
        '~/files/sparc-datasets/55c5b69c-a5b8-4881-a105-e4048af26fa5/SPARC/'
        'Quantified morphology of the human vagus nerve with anti-claudin-1/'
    )
    drp = 'derivative/CadaverVNMorphology_OutputMetrics.mat'
    p = _dsp + drp
    _p = aug.AugmentedPath(_dsp + 'samples.xlsx').expanduser().resolve()
    sp = SamplesFilePath(_p)
    ap = Path(p).expanduser()
    if ap.is_broken_symlink():
        cp = ap.cache.local_object_cache_path
        if not cp.exists():
            pb = {'dataset_id': dataset_id,
                  'remote_id': RemoteId(ap.cache_id, file_id=ap.cache_file_id),
                  'dataset_relative_path': drp,}
            cp = path_from_blob(pb)

        m = scipy.io.loadmat(cp)
    else:
        m = scipy.io.loadmat(p)

    obj_uuid = ap.cache_id.split(':')[-1]
    obj_file_id = ap.cache_file_id

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
                    #**vdd,  # FIXME desc quant domain issues here, technically the fascicles are data signatures
                    # also as predicted this will happen, the issue is that we would have to traverse the instance
                    # partonomy when returning anything, probably would have to be an option which is "match instance children"
                    # or something like that, except that that can expand to millions of values ... and technically
                    # all these instances do have the location and they _are_ technically subClassOf part of nerve which
                    # is what our "nerve" desc_inst means ... i guess below things might be rather large in number so
                    # maybe not coordinating them directly is ok for now ... ?
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
            if k in e  # handle vd out for fasc for now
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


def path_from_blob(pb):
    dataset_id = pb['dataset_id']
    remote_id = pb['remote_id']
    # sparcron and viewer have different defaults
    # check to see if we have a local copy of the file
    from sparcur.config import auth
    from sparcur.paths import Path
    viewer_default = pathlib.Path('~/files/sparc-datasets').expanduser().resolve()
    sparcron_default = pathlib.Path('~/files/sparc-datasets-test').expanduser().resolve()
    config_value = auth.get_path('data-path')
    bases = viewer_default, sparcron_default, config_value
    # see if a file exists in all places, if it doesn't exist in any, fetch it to the first one where the dataset has been fetched at all
    # if none exist anywhere, who knows ... maybe we just hardlink these somewhere common or something e.g. ~/files/sparc-objects
    # and follow the objects database cache approach or something, unfortunately there isn't any easy way to get back to the dataset
    # from the package or even the metadata ... but that's probably ok ???? sigh
    def getstuff():
        dofetch = []
        for p in bases:
            if p is None:
                continue

            db = p / dataset_id.uuid
            if not db.exists():
                continue

            u = remote_id.uuid
            # FIXME we probably want to derive this from cache path or something in case it drifts ...
            rdp = (db / 'dataset').resolve()
            rdrp = rdp / pb['dataset_relative_path']
            prdrp = Path(rdrp)
            cache = prdrp.cache
            if cache is None:
                if not prdrp.exists() and not prdrp.is_broken_symlink():
                    log.error(f'likely out of sync since {prdrp} is missing in the local version at {p}')
                    continue
                else:
                    breakpoint()
                    raise NotImplementedError('wat')

            locp = cache.local_object_cache_path
            if locp.exists():
                return None, locp
            else:
                dofetch.append((cache, locp))

        return dofetch, None

    dofetch, locp = getstuff()
    if locp is not None:
        return locp

    if not dofetch:
        from sparcur.simple.retrieve import main as retrieve
        p = Path(bases[0])
        if not p.exists():
            p.mkdir(parents=True)

        db = p / dataset_id.uuid
        project_id = RemoteId('N:organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0')  # FIXME sigh
        retrieve(dataset_id, dataset_id, project_id=project_id, parent_parent_path=p)
        dofetch, locp = getstuff()
        if locp is not None:
            return locp

    if dofetch:
        cache, locp = dofetch[0]
        cache.fetch(size_limit_mb=30)
        return locp
    else:
        breakpoint()
        raise NotImplementedError('TODO')


class AsIs:
    @classmethod
    def fromJson(cls, blob):
        return blob


register_type(AsIs, 'quantity')  # HACK


def extract_fasc_fib(dataset_uuid, source_local=True):

    dataset_id = RemoteId('dataset:' + dataset_uuid)
    resp_dataset = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/curation-export.json')
    blob_dataset = resp_dataset.json()
    ir_dataset = fromJson(blob_dataset)

    resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')
    blob = resp.json()
    for j in blob['data']:
        j['type'] = 'pathmeta'

    ir = fromJson(blob)
    updated_transitive = max([i['timestamp_updated'] for i in ir['data'][1:]])  # 1: to skip the dataset object itself
    def match_fasc(pb):
        return pb['basename'].endswith('fascicles.csv')

    def match_fib(pb):
        # fasc-*/*fibers.csv are redundant with the merged files
        drp = pb['dataset_relative_path']
        return pb['basename'].endswith('fibers.csv') and not drp.parts[-2].startswith('fasc-')

    # FIXME this is a hacked way to find the files we want, the proper way is to
    # use the metadata sheets

    csvs = [p for p in ir['data'] if 'mimetype' in p and p['mimetype'] == 'text/csv']
    fascs = [p for p in csvs if match_fasc(p)]
    fibs = [p for p in csvs if match_fib(p)]
    other = [p for p in csvs if not match_fasc(p) and not match_fib(p)]
    faps = [path_from_blob(p) for p in fascs]
    fips = [path_from_blob(p) for p in fibs]

    #from neurondm.models.composer import get_csv_sheet
    import csv
    def get_csv_sheet(path):
        with open(path, 'rt') as f:
            _rows = list(csv.reader(f))

        return _rows

    facs = [get_csv_sheet(f) for f in faps]
    fics = [get_csv_sheet(f) for f in fips]

    # headers
    fah = set([tuple(f[0]) for f in facs])
    fih = set([tuple(f[0]) for f in fics])  # looks like the order was different every time somehow !?
    #_wat = set([frozenset(f[0]) for f in fics])  # ok that's a bit better?
    #_sfih = set(h for f in fics for h in set(f[0]))
    #[('tabular-header', f) for f in sorted(_sfih)]

    # ids
    faids = set(pb['remote_id'] for pb in fascs)
    fiids = set(pb['remote_id'] for pb in fibs)

    # uuids
    fau = [pb['remote_id'].uuid for pb in fascs]
    fiu = [pb['remote_id'].uuid for pb in fibs]
    # 1e73e75e-b582-4985-b1ff-609c1e0fddc4  # is a dataset !??! no ??? must have been some bad data creeping in?

    exts = [ext_pmeta(j, ir_dataset, pps) for j in fascs + fibs]
    # FIXME ah the joys of metadata only specimens and my dumb hack to use just the paths
    ext_contents = {f['remote_id']: c for f, c in zip(fascs + fibs, facs + fics)}  # FIXME sort out fasc-n/*fibers.csv vs fibers.csv

    debug_done = set()
    fasc_fib_id = defaultdict(lambda:0)
    def process_record(e, idx, record, header):
        # idx is the record index and it is passed because often the index is implicitly
        # the only way we would be able to uniquely identify and instance (up to an isomorphism)

        # this is where we would integrate using the addresses to look stuff up automatically
        # and I think we would do it by passing in transforms on void, vocd, and voqd that
        # provided that actual addresses
        if e['object'] in faids:  # FIXME horribly inefficient
            # instance
            idx_inst = header.index('fascicle')
            id_inst = record[idx_inst]
            fbase = e['sample'] if e['site'] is None else e['site']  # FIXME overlapping sites -> duplicate fasc issues ...
            id_formal = 'fasc-' + fbase + '-' + str(id_inst)
            di = 'fascicle-cross-section'

            # parent
            #parent_rec = e['dataset'], id_formal, e['sample']  # FIXME technically correct but skips sites
            parent_rec = e['dataset'], id_formal, fbase  # go via site for sanity

            # values q
            # FIXME obvs sync with voqd somehow, probably top down though since mapping the header names
            # is the core of voqd, but we don't want to access the db yet ... the fact that we also need
            # things like unit and aspect addresses etc. means we really want voqd not just this
            addresses = (
                'area',
                'longest_diameter',
                'shortest_diameter',
                'eff_diam',

                'c_estimate_nav',
                'c_estimate_nf',
                'nfibers_all',

                'n_a_alpha',
                'n_a_beta',
                'n_a_gamma',
                'n_a_delta',
                'n_b',
                'n_unmyel_nf',
                'n_nav',
                'n_chat',
                'n_myelinated',

                'area_a_alpha',
                'area_a_beta',
                'area_a_gamma',
                'area_a_delta',
                'area_b',
                'area_unmyel_nf',
                'area_nav',
                'area_chat',
                'area_myelinated',

                         )  # XXX keep in sync with voqd for now
            vsq = []
            for address in addresses:
                idx_v = header.index(address)  # technically correct but if schema is same we don't have to recompute ... ah well
                value = record[idx_v]
                desc_quant = address  # FIXME yeah, exactly why we want voqd, but maybe we fill it later
                # FIXME also int/float conversion should be coming form desc_quant ...
                vr = (value, e['object'].uuid, di, desc_quant, (e['dataset'].uuid, id_formal), value)
                vsq.append(vr)

            # values c
            addresses = tuple()
            vsc = []
            for address in addresses:
                idx_v = header.index(address)
                value = record[idx_v]
                desc_cat = address
                vr = (value, e['object'].uuid, di, desc_cat, (e['dataset'].uuid, id_formal), value)
                vsc.append(vr)

            yield id_formal, {
                'type': 'below',
                'desc_inst': di,
                'id_sub': e['subject'],
                'id_sam': e['sample'],
             }, parent_rec, vsq, vsc

        elif e['object'] in fiids:
            if False:
                if e['object'] in debug_done:
                    # avoid universe destroying debug message
                    return

                debug_done.add(e['object'])

            _fasc = e['fasc']
            fasc_id = None if _fasc is None else _fasc.split('-')[-1]
            if 'fascicle' in header:
                # FIXME there are 4 different header variants
                # for fibers, so we have to know which one is
                # which otherwise we will violate constraints
                _idx_inst = header.index('fascicle')
                _id_inst = record[_idx_inst]
                _fasc_id = str(_id_inst)
                if fasc_id is not None and _fasc_id != fasc_id:
                    log.error(f'??? {_fasc_id} != {fasc_id}')
                _fbase = e['sample'] if e['site'] is None else e['site']
                fbase = 'fasc-' + _fbase + '-' + _fasc_id
                fasc_fib_id[(e['dataset'], fbase)] += 1
                id_inst = fasc_fib_id[(e['dataset'], fbase)]
            else:
                # FIXME this will cause inconsistencies between levels of fibers files even though the row ordering is consistent
                id_inst = idx + 1
                fbase = e['sample'] if e['site'] is None else e['site']
                if fasc_id is not None:
                    fbase = 'fasc-' + fbase + '-' + fasc_id

            id_formal = 'fiber-' + fbase + '-' + str(id_inst)
            di = 'fiber-cross-section'
            parent_rec = e['dataset'], id_formal, fbase

            # values q
            addresses = (
                'fiber_area',
                'longest_diameter',
                'shortest_diameter',
                'eff_fib_diam',

            )  # XXX keep in sync with voqd for now
            vsq = []
            for address in addresses:
                idx_v = header.index(address)  # technically correct but if schema is same we don't have to recompute ... ah well
                value = record[idx_v]
                desc_quant = address  # FIXME yeah, exactly why we want voqd, but maybe we fill it later
                # FIXME also int/float conversion should be coming form desc_quant ...
                vr = (value, e['object'].uuid, di, desc_quant, (e['dataset'].uuid, id_formal), value)
                vsq.append(vr)

            # values c
            addresses = ('myelinated',)
            vsc = []
            for address in addresses:
                idx_v = header.index(address)
                value = 'myelinated' if record[idx_v].lower() == 'true' else 'unmyelinated'
                desc_cat = address
                vr = (value, e['object'].uuid, di, desc_cat, (e['dataset'].uuid, id_formal))
                vsc.append(vr)

            yield id_formal, {
                'type': 'below',
                'desc_inst': di,
                'id_sub': e['subject'],
                'id_sam': e['sample'],
             }, parent_rec, vsq, vsc

    (instances, _parents, objects, values_objects, values_dataset_object, values_q, values_c
     ) = ext_values(exts, ext_contents, ir_dataset, process_record)

    parents_sam = [(dataset_id, s['sample_id'], p)
                   for s in ir_dataset['samples']
                   for p in (s['was_derived_from'] if 'was_derived_from' in s else (s['subject_id'],))]

    # FIXME technically sites are orthognoal to the instance hierarchy ... I'm including them
    # but the fasc and fib level tends to go to sample directly and I think that is actually reasonable
    parents_site = [(dataset_id, s['site_id'], s['specimen_id']) for s in ir_dataset['sites']]

    _uns_parents = parents_sam + parents_site + _parents
    parents = sort_parents(set(_uns_parents))
    #check_parents_instances(instances, parents)  # figure out the issue was bad ordering of inserts

    if len(_uns_parents) != len(parents):
        qq = [(a, b) for a, b in Counter(_uns_parents).most_common() if b > 1]
        #usually ok
        log.warning(f'duplicate parents {qq}!')

    def make_values_instances(i):
        values_instances = [
            (d.uuid,
             id_formal,
             inst['type'],
             i.luid[inst['desc_inst']],
             inst['id_sub'] if 'id_sub' in inst else None,
             inst['id_sam'] if 'id_sam' in inst else None,
             )
            for (d, id_formal), inst in instances.items()
        ]
        return values_instances

    def make_values_parents(luinst):
        values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        void = []
        for obj_uuid in fau:
            # desc_ins address None because it comes from outer context and addresses are for inner?
            # or was i trying to do something fancy with that ... e.g. to query cases where datasets
            # were missing info
            void.append((obj_uuid, i.id_fascicle_cross_section, i.addr_fascicle, None))
        for obj_uuid in fiu:
            void.append((obj_uuid, i.id_fiber_cross_section, i.addr_index, None))

        return void

    inv_vocd = {}
    def make_vocd(this_dataset_updated_uuid, i):
        vocd = []
        for obj_uuid in fiu:
            vocd.append((obj_uuid, i.cd_axon, i.addr_myelinated))

        inv = {(i._q._inv['addr', a]['fadd'], u in fiu):(q, a) for u, q, a in vocd}
        inv_vocd.update(inv)
        return vocd

    voqd_mapping = (
        ('fascicle cross section area um2', 'area'),
        ('fascicle cross section diameter um max', 'longest_diameter'),
        ('fascicle cross section diameter um min', 'shortest_diameter'),
        ('fascicle cross section diameter um', 'eff_diam'),
        ('nav fiber count in fascicle cross section estimated', 'c_estimate_nav'),
        ('fiber count in fascicle cross section estimated', 'c_estimate_nf'),
        ('fiber count in fascicle cross section', 'nfibers_all'),
        ('alpha a fiber count in fascicle cross section', 'n_a_alpha'),
        ('beta a fiber count in fascicle cross section', 'n_a_beta'),
        ('gamma a fiber count in fascicle cross section', 'n_a_gamma'),
        ('delta a fiber count in fascicle cross section', 'n_a_delta'),
        ('b fiber count in fascicle cross section', 'n_b'),
        ('unmyelinated fiber count in fascicle cross section', 'n_unmyel_nf'),
        ('nav fiber count in fascicle cross section', 'n_nav'),
        ('chat fiber count in fascicle cross section', 'n_chat'),
        ('myelinated fiber count in fascicle cross section', 'n_myelinated'),
        ('alpha a fiber area in fascicle cross section um2', 'area_a_alpha'),
        ('beta a fiber area in fascicle cross section um2', 'area_a_beta'),
        ('gamma a fiber area in fascicle cross section um2', 'area_a_gamma'),
        ('delta a fiber area in fascicle cross section um2', 'area_a_delta'),
        ('b fiber area in fascicle cross section um2', 'area_b'),
        ('unmyelinated fiber area in fascicle cross section um2', 'area_unmyel_nf'),
        ('nav fiber area in fascicle cross section um2', 'area_nav'),
        ('chat fiber area in fascicle cross section um2', 'area_chat'),
        ('myelinated fiber area in fascicle cross section um2', 'area_myelinated'),
    )
    inv_voqd = {}
    def make_voqd(this_dataset_updated_uuid, i):
        voqd = []
        for obj_uuid in fau:
            for qd, a in voqd_mapping:
                iqd, ia = i.reg_qd(qd), i.reg_addr(a)  # FIXME caching is nice but we should be able to reg once and not have to hit the cache at all
                voqd.append((obj_uuid, iqd, ia))

        # FIXME likely need to deal with cases where there are missing columns :/
        for obj_uuid in fiu:
            voqd.extend((
                (obj_uuid, i.qd_fiber_cs_area_um2, i.addr_fiber_area),
                (obj_uuid, i.qd_fiber_cs_diameter_um_max, i.addr_long_diam),
                (obj_uuid, i.qd_fiber_cs_diameter_um_min, i.addr_short_diam),
                (obj_uuid, i.qd_fiber_cs_diameter_um, i.addr_eff_fib_diam),
            ))

        inv = {(i._q._inv['addr', a]['fadd'], u in fiu):(q, a) for u, q, a in voqd}
        inv_voqd.update(inv)
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        values_cv = []
        #for obj_uuid in fau:  # not really any for this one
        #for obj_uuid in fau:
        for value, o_uuid, di, addr, inst_ident in values_c:
            desc_cat, _ = inv_vocd[addr, o_uuid in fiu]
            desc_inst = i.luid[di]
            values_cv.append(
                (None,
                 i.luct[value],
                 o_uuid,
                 desc_inst,
                 desc_cat,
                 luinst[inst_ident],
                 )
            )

        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        values_qv = []
        #breakpoint()
        #hack_di = {'fascicle-cross-section': i.id_fascicle_cross_section}
        #hack_addr = {'area': i.addr_area}  # FIXME so much duplication oof
        for value, o_uuid, di, addr, inst_ident, value_blob in values_q:
            desc_quant, _ = inv_voqd[addr, o_uuid in fiu]
            desc_inst = i.luid[di]  # i._q._inv['id', di]
            values_qv.append(
                (value,
                 o_uuid,
                 desc_inst,
                 desc_quant,
                 luinst[inst_ident],
                 value_blob,))
        # (value, object, desc_inst, desc_quant, instance, value_blob)
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
        # this is effectively where we specify the schema
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


def ingest_fasc_fib(session, source_local=True, do_insert=True, commit=False, dev=False):
    #dataset_uuid = 'ec6ad74e-7b59-409b-8fc7-a304319b6faf'  # f003
    dataset_uuid = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'  # f006
    ingest(dataset_uuid, extract_fasc_fib, session, commit=commit, dev=dev)


def ingest_reva_ft_all(session, source_local=False, do_insert=True, batch=False, commit=False, dev=False):
    dataset_uuids = (
        '2a3d01c0-39d3-464a-8746-54c9d67ebe0f',  # f006
    )
    (
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


def main(source_local=False, commit=False, echo=False):
    from quantdb.config import auth

    dbkwargs = {k: auth.get(f'db-{k}') for k in ('user', 'host', 'port', 'database')}  # TODO integrate with cli options
    dbkwargs['dbuser'] = dbkwargs.pop('user')
    engine = create_engine(dbUri(**dbkwargs), query_cache_size=0)
    log.info(engine)
    engine.echo = echo
    session = Session(engine)

    do_all = False
    do_fasc_fib = False or do_all
    do_reva_ft = False or do_all
    do_demo_jp2 = False or do_all
    do_demo = False or do_all

    if do_fasc_fib:
        try:
            ingest_fasc_fib(session, source_local=source_local, do_insert=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    if do_reva_ft:
        try:
            ingest_reva_ft_all(session, source_local=source_local, do_insert=True, batch=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    if do_demo_jp2:
        try:
            ingest_demo_jp2(session, source_local=source_local, do_insert=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    if do_demo:
        try:
            ingest_demo(session, source_local=source_local, do_insert=True, commit=commit, dev=True)
        except Exception as e:
            session.rollback()
            session.close()
            engine.dispose()
            raise e

    session.close()
    engine.dispose()
    log.info('ingest done')


if __name__ == '__main__':
    main()
