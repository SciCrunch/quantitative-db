"""Data extraction functions for the v2 ingest pipeline.

Parses cassava curation-export.json metadata and produces flat dicts
ready for ``Ingest.batch()``.  All FK columns use string labels
(e.g. ``desc_inst='nerve-volume'``) rather than integer IDs.
"""
from __future__ import annotations

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
