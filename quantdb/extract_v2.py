"""Data extraction functions for the v2 ingest pipeline.

Parses cassava curation-export.json metadata and produces flat dicts
ready for ``Ingest.batch()``.  All FK columns use string labels
(e.g. ``desc_inst='nerve-volume'``) rather than integer IDs.
"""
from __future__ import annotations

import pathlib
from collections import defaultdict, deque

# ---------------------------------------------------------------------------
# Translation tables (mirroring legacy ingest.py)
# ---------------------------------------------------------------------------

_TRANSLATE_SPECIES = {
    'ncbitaxon:9606': 'human',
    'http://purl.obolibrary.org/obo/NCBITaxon_9606': 'human',
}

_TRANSLATE_SAMPLE_TYPE = {
    'nerve': 'nerve',
    'segment': 'nerve-volume',
    'subsegment': 'nerve-volume',
    'section': 'nerve-cross-section',
    'virtual': 'simulation',
}

_TRANSLATE_SITE_TYPE = {
    'extruded plane': 'extruded-plane',
}


def _translate_species(v):
    """Translate a species value (dict or string) to a desc_inst label."""
    if isinstance(v, dict):
        v = v['id']

    # normalise to lowercase for lookup
    key = v.lower() if isinstance(v, str) else v
    if key in _TRANSLATE_SPECIES:
        return _TRANSLATE_SPECIES[key]

    # try as-is
    return _TRANSLATE_SPECIES[v]


def _translate_sample_type(v):
    """Translate sample_type string to a desc_inst label."""
    return _TRANSLATE_SAMPLE_TYPE[v]


def _translate_site_type(v):
    """Translate site_type string to a desc_inst label."""
    return _TRANSLATE_SITE_TYPE[v]


# ---------------------------------------------------------------------------
# Topological sort helper
# ---------------------------------------------------------------------------

def _topo_sort_samples(raw_samples, parents_list):
    """Return *raw_samples* reordered so that parent samples appear first.

    ``parents_list`` is a list of ``(child_id, parent_id)`` tuples.
    Only parent relationships where both child and parent are samples
    are considered for ordering.
    """
    id_to_sample = {s['id_formal']: s for s in raw_samples}
    sample_ids = set(id_to_sample)

    # Build adjacency: parent → children (within sample set only)
    children_of = defaultdict(list)
    parent_of = defaultdict(list)
    for child_id, parent_id in parents_list:
        if child_id in sample_ids and parent_id in sample_ids:
            children_of[parent_id].append(child_id)
            parent_of[child_id].append(parent_id)

    # Kahn's algorithm (BFS topological sort)
    in_degree = {sid: 0 for sid in sample_ids}
    for child_id, parent_id in parents_list:
        if child_id in sample_ids and parent_id in sample_ids:
            in_degree[child_id] += 1

    queue = deque(sorted(sid for sid in sample_ids if in_degree[sid] == 0))
    ordered = []
    while queue:
        node = queue.popleft()
        ordered.append(id_to_sample[node])
        for child in sorted(children_of[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Sanity: any remaining samples (shouldn't happen with valid data)
    seen = {s['id_formal'] for s in ordered}
    for s in raw_samples:
        if s['id_formal'] not in seen:
            ordered.append(s)

    return ordered


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_entities_v2(curation_export, dataset_uuid):
    """Extract entity metadata from a single dataset's curation-export.json.

    Parameters
    ----------
    curation_export : dict
        Parsed curation-export.json for one dataset.
    dataset_uuid : str
        The dataset UUID string.

    Returns
    -------
    dict
        Keys ``'subjects'``, ``'samples'``, ``'sites'``, ``'parents'``.
        Each value is a list of flat dicts with string FK labels,
        ready for ``Ingest.batch()``.
    """
    subjects = []
    raw_samples = []
    sites = []
    parents = []  # list of {'child': id_formal, 'parent': id_formal}

    # Build sample_id → subject_id lookup for site subject resolution
    sample_subject = {
        s['sample_id']: s['subject_id']
        for s in curation_export.get('samples', [])
    }

    # -------------------------------------------------------------------
    # Subjects
    # -------------------------------------------------------------------
    for ent in curation_export.get('subjects', []):
        species = ent.get('species')
        desc_inst = _translate_species(species) if species else None

        subjects.append({
            'dataset': dataset_uuid,
            'id_formal': ent['subject_id'],
            'type': 'subject',
            'desc_inst': desc_inst,
            'id_sub': ent['subject_id'],
        })

    # -------------------------------------------------------------------
    # Samples
    # -------------------------------------------------------------------
    # Collect raw parent edges for topological sorting
    sample_parent_edges = []  # (child_id, parent_id)

    for ent in curation_export.get('samples', []):
        sample_id = ent['sample_id']

        # Determine parent(s)
        wdf = ent.get('was_derived_from')
        if wdf:
            if isinstance(wdf, list):
                for p in wdf:
                    parents.append({'child': sample_id, 'parent': p})
                    sample_parent_edges.append((sample_id, p))
            else:
                parents.append({'child': sample_id, 'parent': wdf})
                sample_parent_edges.append((sample_id, wdf))
        else:
            # Fall back to subject_id as parent
            parents.append({'child': sample_id, 'parent': ent['subject_id']})
            sample_parent_edges.append((sample_id, ent['subject_id']))

        # Translate sample_type to desc_inst
        sample_type = ent.get('sample_type')
        desc_inst = _translate_sample_type(sample_type) if sample_type else None

        raw_samples.append({
            'dataset': dataset_uuid,
            'id_formal': sample_id,
            'type': 'sample',
            'desc_inst': desc_inst,
            'id_sub': ent['subject_id'],
            'id_sam': sample_id,
        })

    # Topologically sort samples so parents appear before children
    samples = _topo_sort_samples(raw_samples, sample_parent_edges)

    # -------------------------------------------------------------------
    # Sites
    # -------------------------------------------------------------------
    for ent in curation_export.get('sites', []):
        site_id = ent['site_id']
        specimen_id = ent['specimen_id']

        # Resolve subject: if specimen_id is a subject use directly,
        # otherwise look up the sample's subject_id.
        if specimen_id.startswith('sub-'):
            id_sub = specimen_id
        else:
            id_sub = sample_subject.get(specimen_id)

        rec = {
            'dataset': dataset_uuid,
            'id_formal': site_id,
            'type': 'site',
            'desc_inst': _translate_site_type(ent['site_type']),
            'id_sub': id_sub,
        }

        # If specimen is a sample, record id_sam
        if specimen_id.startswith('sam-'):
            rec['id_sam'] = specimen_id

        sites.append(rec)
        parents.append({'child': site_id, 'parent': specimen_id})

    return {
        'subjects': subjects,
        'samples': samples,
        'sites': sites,
        'parents': parents,
    }


# ---------------------------------------------------------------------------
# Fascicle / Fiber descriptor addresses (mirroring legacy ingest.py)
# ---------------------------------------------------------------------------

# Column names in fascicles.csv → descriptor labels for quant values.
# Kept in sync with legacy ``process_record`` addresses tuple.
_FASCICLE_QUANT_COLUMNS = (
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
)

# Column names in fibers.csv → descriptor labels for quant values.
_FIBER_QUANT_COLUMNS = (
    'fiber_area',
    'longest_diameter',
    'shortest_diameter',
    'eff_fib_diam',
)

# Categorical column for fibers.
_FIBER_CAT_COLUMN = 'myelinated'


# ---------------------------------------------------------------------------
# Path-metadata parsing helpers
# ---------------------------------------------------------------------------

def _parse_csv_path(dataset_relative_path, curation_export):
    """Parse a CSV file's dataset-relative path to extract context.

    Mirrors the legacy ``pps()`` function logic for CSV files.

    Returns
    -------
    dict with keys: subject, sample, site, site_type, fasc
    """
    parts = pathlib.PurePosixPath(dataset_relative_path).parts
    site = None
    site_type = None
    fasc = None

    if len(parts) == 6:
        # primary/subject/nerve/segment/fasc-N/file.csv
        _top, subject, _sam_1, segment, modality, _file = parts
        if segment.startswith('site-'):
            site = segment
            site_meta = [s for s in curation_export.get('sites', [])
                         if s['site_id'] == site]
            if site_meta:
                site_type = _translate_site_type(site_meta[0]['site_type'])
                segment = site_meta[0]['specimen_id']
        if modality.startswith('fasc-'):
            fasc = modality

    elif len(parts) == 5:
        _top, subject, _sam_1, segment, _file = parts
        if segment.startswith('site-'):
            site = segment
            site_meta = [s for s in curation_export.get('sites', [])
                         if s['site_id'] == site]
            if site_meta:
                site_type = _translate_site_type(site_meta[0]['site_type'])
                segment = site_meta[0]['specimen_id']

    else:
        return None

    return {
        'subject': subject,
        'sample': segment,
        'site': site,
        'site_type': site_type,
        'fasc': fasc,
    }


def _extract_uuid(remote_id):
    """Extract bare UUID string from a remote_id like 'package:UUID'."""
    s = str(remote_id)
    if ':' in s:
        return s.rsplit(':', 1)[-1]
    return s


def _extract_file_id(entry):
    """Extract integer file_id from a path-metadata entry."""
    fid = entry.get('file_id')
    if fid is not None:
        return int(fid)
    uri = entry.get('uri_api', '')
    if uri:
        return int(uri.rsplit('/', 1)[-1])
    return None


# ---------------------------------------------------------------------------
# JPX / microCT file extraction
# ---------------------------------------------------------------------------

def extract_reva_ft_v2(path_metadata):
    """Extract JPX/microCT file objects from path-metadata.json.

    Parameters
    ----------
    path_metadata : dict
        Parsed path-metadata.json with a ``'data'`` list.

    Returns
    -------
    dict
        Key ``'objects'``: list of dicts, each with ``'uuid'``,
        ``'file_id'``, ``'id_type'``.
    """
    objects = []
    for entry in path_metadata.get('data', []):
        if entry.get('mimetype') != 'image/jpx':
            continue

        uuid = _extract_uuid(entry.get('remote_id', ''))
        file_id = _extract_file_id(entry)

        objects.append({
            'uuid': uuid,
            'file_id': file_id,
            'id_type': 'package',
        })

    return {'objects': objects}


# ---------------------------------------------------------------------------
# Fascicle / Fiber CSV extraction
# ---------------------------------------------------------------------------

def _find_csv_entries(path_metadata):
    """Find all CSV file entries in path-metadata by mimetype or basename."""
    entries = []
    for entry in path_metadata.get('data', []):
        mimetype = entry.get('mimetype', '')
        basename = entry.get('basename', '')
        if mimetype == 'text/csv' or basename.endswith('.csv'):
            entries.append(entry)
    return entries


def _is_fasc_subfolder_fiber(entry):
    """Return True if a fibers.csv is inside a fasc-N/ subfolder.

    These per-fascicle fiber files are redundant with the merged
    fibers.csv at the sample/site level.
    """
    drp = str(entry.get('dataset_relative_path', ''))
    parts = pathlib.PurePosixPath(drp).parts
    if len(parts) >= 2:
        parent_dir = parts[-2]
        return parent_dir.startswith('fasc-')
    return False


def extract_fasc_fib_v2(curation_export, path_metadata, dataset_uuid, csv_fetcher):
    """Extract fascicle and fiber data from CSV files.

    Parameters
    ----------
    curation_export : dict
        Parsed curation-export.json for the dataset.
    path_metadata : dict
        Parsed path-metadata.json with ``'data'`` list.
        CSV entries must have ``'basename'``, ``'dataset_relative_path'``,
        ``'remote_id'`` keys.
    dataset_uuid : str
        The dataset UUID string.
    csv_fetcher : callable
        ``csv_fetcher(blob)`` receives a path-metadata entry dict and
        returns CSV rows as a list of lists (header + data rows).

    Returns
    -------
    dict
        Keys: ``'fascicles'``, ``'fibers'``, ``'parents'``,
        ``'objects'``, ``'quant_values'``, ``'cat_values'``.
    """
    csv_entries = _find_csv_entries(path_metadata)

    fasc_entries = [e for e in csv_entries
                    if e.get('basename', '').endswith('fascicles.csv')]
    fib_entries = [e for e in csv_entries
                   if e.get('basename', '').endswith('fibers.csv')
                   and not _is_fasc_subfolder_fiber(e)]

    fascicles = []
    fibers = []
    parents = []   # list of {'child': id_formal, 'parent': id_formal}
    objects = {}   # uuid -> {'id_type': ..., 'file_id': ...}
    quant_values = []
    cat_values = []

    # Track fiber-per-fascicle counters (mirrors legacy fasc_fib_id)
    fasc_fib_id = defaultdict(int)

    # Build sample_subject lookup from curation_export
    sample_subject = {
        s['sample_id']: s['subject_id']
        for s in curation_export.get('samples', [])
    }

    # Collect fascicle remote_ids for later fiber classification
    fasc_remote_ids = set()
    for entry in fasc_entries:
        rid = _extract_uuid(entry.get('remote_id', ''))
        fasc_remote_ids.add(rid)

    # Collect fiber remote_ids
    fib_remote_ids = set()
    for entry in fib_entries:
        rid = _extract_uuid(entry.get('remote_id', ''))
        fib_remote_ids.add(rid)

    # ------------------------------------------------------------------
    # Process fascicle CSV files
    # ------------------------------------------------------------------
    for entry in fasc_entries:
        ctx = _parse_csv_path(
            entry.get('dataset_relative_path', ''), curation_export)
        if ctx is None:
            continue

        obj_uuid = _extract_uuid(entry.get('remote_id', ''))
        file_id = _extract_file_id(entry)
        objects[obj_uuid] = {'id_type': 'package', 'file_id': file_id}

        rows = csv_fetcher(entry)
        if not rows:
            continue

        header = rows[0]

        # Determine fbase (site if available, else sample)
        fbase = ctx['site'] if ctx['site'] is not None else ctx['sample']

        # Resolve subject
        subject = ctx['subject']
        sample = ctx['sample']
        id_sub = subject
        id_sam = sample

        for i, record in enumerate(rows[1:]):
            # Fascicle id from the 'fascicle' column
            idx_inst = header.index('fascicle')
            fascicle_id = record[idx_inst]
            id_formal = 'fasc-' + fbase + '-' + str(fascicle_id)

            fascicles.append({
                'dataset': dataset_uuid,
                'id_formal': id_formal,
                'type': 'below',
                'desc_inst': 'fascicle-cross-section',
                'id_sub': id_sub,
                'id_sam': id_sam,
            })

            # Parent: fascicle -> site/sample
            parents.append({'child': id_formal, 'parent': fbase})

            # Quantitative values
            for col_name in _FASCICLE_QUANT_COLUMNS:
                if col_name in header:
                    idx_v = header.index(col_name)
                    value = record[idx_v]
                    quant_values.append({
                        'value': value,
                        'value_blob': value,
                        'object': obj_uuid,
                        'desc_inst': 'fascicle-cross-section',
                        'desc_quant': col_name,
                        'instance': {
                            'dataset': dataset_uuid,
                            'id_formal': id_formal,
                        },
                    })

    # ------------------------------------------------------------------
    # Process fiber CSV files
    # ------------------------------------------------------------------
    for entry in fib_entries:
        ctx = _parse_csv_path(
            entry.get('dataset_relative_path', ''), curation_export)
        if ctx is None:
            continue

        obj_uuid = _extract_uuid(entry.get('remote_id', ''))
        file_id = _extract_file_id(entry)
        objects[obj_uuid] = {'id_type': 'package', 'file_id': file_id}

        rows = csv_fetcher(entry)
        if not rows:
            continue

        header = rows[0]

        subject = ctx['subject']
        sample = ctx['sample']
        id_sub = subject
        id_sam = sample
        _fasc = ctx.get('fasc')
        fasc_id_from_path = None if _fasc is None else _fasc.split('-')[-1]

        for i, record in enumerate(rows[1:]):
            # Determine fbase and fiber index
            if 'fascicle' in header:
                _idx_inst = header.index('fascicle')
                _id_inst = record[_idx_inst]
                _fasc_id = str(_id_inst)
                _fbase = (ctx['site'] if ctx['site'] is not None
                          else ctx['sample'])
                fbase = 'fasc-' + _fbase + '-' + _fasc_id
                fasc_fib_id[(dataset_uuid, fbase)] += 1
                id_inst = fasc_fib_id[(dataset_uuid, fbase)]
            else:
                id_inst = i + 1
                fbase = (ctx['site'] if ctx['site'] is not None
                         else ctx['sample'])
                if fasc_id_from_path is not None:
                    fbase = 'fasc-' + fbase + '-' + fasc_id_from_path

            id_formal = 'fiber-' + fbase + '-' + str(id_inst)

            fibers.append({
                'dataset': dataset_uuid,
                'id_formal': id_formal,
                'type': 'below',
                'desc_inst': 'fiber-cross-section',
                'id_sub': id_sub,
                'id_sam': id_sam,
            })

            # Parent: fiber -> fascicle (or site/sample)
            parents.append({'child': id_formal, 'parent': fbase})

            # Quantitative values
            for col_name in _FIBER_QUANT_COLUMNS:
                if col_name in header:
                    idx_v = header.index(col_name)
                    value = record[idx_v]
                    quant_values.append({
                        'value': value,
                        'value_blob': value,
                        'object': obj_uuid,
                        'desc_inst': 'fiber-cross-section',
                        'desc_quant': col_name,
                        'instance': {
                            'dataset': dataset_uuid,
                            'id_formal': id_formal,
                        },
                    })

            # Categorical value: myelinated
            if _FIBER_CAT_COLUMN in header:
                idx_v = header.index(_FIBER_CAT_COLUMN)
                raw = record[idx_v]
                value = ('myelinated' if str(raw).lower() == 'true'
                         else 'unmyelinated')
                cat_values.append({
                    'value': value,
                    'object': obj_uuid,
                    'desc_inst': 'fiber-cross-section',
                    'desc_cat': _FIBER_CAT_COLUMN,
                    'instance': {
                        'dataset': dataset_uuid,
                        'id_formal': id_formal,
                    },
                })

    return {
        'fascicles': fascicles,
        'fibers': fibers,
        'parents': parents,
        'objects': objects,
        'quant_values': quant_values,
        'cat_values': cat_values,
    }
