#!/usr/bin/env python3
"""
F006 Dataset Ingestion - Full Implementation

Uses automap_base for dynamic model reflection. Processes cached CSV files
to create fiber/fascicle instances and quantitative values.

Dataset: 2a3d01c0-39d3-464a-8746-54c9d67ebe0f (Human vagus nerve microCT/IHC)
"""

import csv
import json
import pathlib
import uuid as uuid_module
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import dateutil.parser
import requests
import yaml
from sqlalchemy import text as sql_text

from quantdb.automap_client import get_automap_session, get_insert_order
from quantdb.generic_ingest import (
    back_populate_with_dependencies,
    create_all_descriptors_from_yaml,
    get_or_create_dynamic,
)

DATASET_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'
DATA_DIR = pathlib.Path(__file__).parent / 'data'
CACHE_DIR = DATA_DIR / 'csv_cache' / DATASET_UUID
MAPPINGS_FILE = pathlib.Path(__file__).parent / 'f006_interlex_mappings.yaml'
CURATION_EXPORT_URL = f'https://cassava.ucsd.edu/sparc/datasets/{DATASET_UUID}/LATEST/curation-export.json'
CURATION_CACHE = DATA_DIR / 'f006_curation_export.json'

# Fiber CSV column mappings to quantitative descriptors
FIBER_QUANT_COLUMNS = {
    'fiber_area': 'fiber cross section area um2',
    'eff_fib_diam': 'fiber cross section diameter um',
    'longest_diameter': 'fiber cross section diameter um max',
    'shortest_diameter': 'fiber cross section diameter um min',
}

# Fiber categorical column
FIBER_CAT_COLUMNS = {
    'myelinated': ('myelinated', 'unmyelinated'),  # True -> myelinated, False -> unmyelinated
}

# Fascicle CSV column mappings to quantitative descriptors (from reference quantdb/ingest.py)
FASCICLE_QUANT_COLUMNS = {
    'area': 'fascicle cross section area um2',
    'longest_diameter': 'fascicle cross section diameter um max',
    'shortest_diameter': 'fascicle cross section diameter um min',
    'eff_diam': 'fascicle cross section diameter um',
    'c_estimate_nav': 'nav fiber count in fascicle cross section estimated',
    'c_estimate_nf': 'fiber count in fascicle cross section estimated',
    'nfibers_all': 'fiber count in fascicle cross section',
    'n_a_alpha': 'alpha a fiber count in fascicle cross section',
    'n_a_beta': 'beta a fiber count in fascicle cross section',
    'n_a_gamma': 'gamma a fiber count in fascicle cross section',
    'n_a_delta': 'delta a fiber count in fascicle cross section',
    'n_b': 'b fiber count in fascicle cross section',
    'n_unmyel_nf': 'unmyelinated fiber count in fascicle cross section',
    'n_nav': 'nav fiber count in fascicle cross section',
    'n_chat': 'chat fiber count in fascicle cross section',
    'n_myelinated': 'myelinated fiber count in fascicle cross section',
    'area_a_alpha': 'alpha a fiber area in fascicle cross section um2',
    'area_a_beta': 'beta a fiber area in fascicle cross section um2',
    'area_a_gamma': 'gamma a fiber area in fascicle cross section um2',
    'area_a_delta': 'delta a fiber area in fascicle cross section um2',
    'area_b': 'b fiber area in fascicle cross section um2',
    'area_unmyel_nf': 'unmyelinated fiber area in fascicle cross section um2',
    'area_nav': 'nav fiber area in fascicle cross section um2',
    'area_chat': 'chat fiber area in fascicle cross section um2',
    'area_myelinated': 'myelinated fiber area in fascicle cross section um2',
}

# Anatomical ordering for segment index calculation (from reference)
SAM_ORDERING = {'l': 1, 'r': 2, 'c': 3}
SEG_ORDERING = {'c': 1, 't': 2, 'l': 3, 's': 4}


def anat_index(sample: str) -> tuple:
    """Calculate anatomical index from sample path."""
    if sample.count('-') < 3:
        sam, sam_id = sample.split('-')
        seg_id = None
    else:
        sam, sam_id, seg, seg_id, *_rest = sample.split('-')

    sam_ind = SAM_ORDERING.get(sam_id, 0)
    if seg_id is None:
        return sam_ind, 0, 0, 0

    for k, v in SEG_ORDERING.items():
        if seg_id.startswith(k):
            prefix = k
            seg_ind = v
            break
    else:
        if sam_id == 'c':
            rest = int(seg_id[:-1]) if seg_id[:-1].isdigit() else 0
            suffix = int(seg_id[-1].encode().hex()) if seg_id[-1].isalpha() else 0
            return sam_ind, 0, rest, suffix
        return sam_ind, 0, 0, 0

    rest = int(seg_id[len(prefix) :]) if seg_id[len(prefix) :].isdigit() else 0
    return sam_ind, seg_ind, rest, 0


def proc_anat(rawind: dict) -> dict:
    """Normalize anatomical indices to 0-1 range with overlap."""
    lin_distinct = {v: i for i, v in enumerate(sorted(set(rawind.values())))}
    max_distinct = len(lin_distinct)
    mdp1 = max_distinct + 0.1
    sindex = {}
    for (d, s), raw in rawind.items():
        pos = lin_distinct[raw]
        inst = (pos + 0.55) / mdp1
        minp = pos / mdp1
        maxp = (pos + 1.1) / mdp1
        sindex[(d, s)] = inst, minp, maxp
    return sindex


# Topological sort functions for parent relationship ordering (from quantdb/ingest.py)
def toposort(adj, unmarked_key=None):
    """Generic topological sort."""
    _dd = defaultdict(list)
    [_dd[a].append(b) for a, b in adj]
    nexts = dict(_dd)

    _keys = set([a for a, b in adj])
    _values = set([b for a, b in adj])

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


def subst_toposort(edges, unmarked_key=None):
    """Substitution-based topological sort for parent relationships."""
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
    """Sorting key for parent tuples (dataset_id, child, parent)."""
    a, b, c = abc
    if b.startswith('sub-'):
        return 0
    elif b.startswith('sam-'):
        if c.startswith('sub-'):
            return 1
        elif c.startswith('sam-'):
            return 2
        else:
            raise ValueError(f'unexpected parent for sample: {abc}')
    elif b.startswith('site-'):
        return 3
    elif b.startswith('fasc-'):
        return 4
    elif b.startswith('fiber-'):
        return 5
    elif b.startswith('nv-'):
        return 6
    else:
        return 9999


def sort_parents(parents):
    """Sort parent relationships with topological ordering for sample-to-sample."""
    if not parents:
        return []

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
        return s_parents

    pre_sasa_parents = s_parents[:b_sam]
    sasa_parents = s_parents[b_sam:] if e_sam is None else s_parents[b_sam:e_sam]
    post_sasa_parents = [] if e_sam is None else s_parents[e_sam:]

    if sasa_parents:
        sord = subst_toposort([((a, b), (a, c)) for a, b, c in sasa_parents])

        def ssord(abc):
            a, b, c = abc
            return sord.index((a, b)), sord.index((a, c))

        ts_sasa = sorted(sasa_parents, key=ssord)
    else:
        ts_sasa = []

    return pre_sasa_parents + ts_sasa + post_sasa_parents


class F006Ingestion:
    """
    Full F006 ingestion using dynamic model reflection.

    This class handles:
    - Loading cached metadata and CSV files
    - Creating schema components from YAML mappings
    - Creating fiber/fascicle instances from CSV data
    - Creating quantitative and categorical values
    """

    def __init__(self, models: dict, yaml_config: dict = None):
        """
        Initialize with reflected models and optional YAML config.

        Parameters
        ----------
        models : dict
            Dictionary mapping table names to model classes from automap.
        yaml_config : dict, optional
            Parsed YAML configuration. Loads from default file if not provided.
        """
        self.models = models
        self.table_order = get_insert_order(models)

        if yaml_config is None and MAPPINGS_FILE.exists():
            with open(MAPPINGS_FILE, 'r') as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = yaml_config or {}

        self.descriptor_ids = {}
        self.instance_lookup = {}
        self.parents = []
        self.values_quant = []
        self.values_cat = []
        self.fiber_count = 0
        self.fascicle_count = 0
        self.jpx_count = 0
        self.pending_fiber_instances = []
        self.pending_fascicle_instances = []
        self.pending_jpx_instances = []
        self.pending_obj_desc_inst = []  # For obj_desc_inst linking
        self.pending_obj_desc_quant = set()  # For obj_desc_quant linking (use set to dedupe)
        self.pending_obj_desc_cat = set()  # For obj_desc_cat linking (use set to dedupe)
        self.pending_dataset_objects = []  # For dataset_object linking (dataset -> package)
        self.site_to_subject = {}  # Site -> subject mapping from curation
        self.site_to_sample = {}  # Site -> sample mapping from curation
        self.path_to_curation_site = {}  # Path site ID -> curation site ID mapping

    def load_metadata(self, metadata_path: pathlib.Path = None) -> dict:
        """Load path metadata from cached JSON file."""
        path = metadata_path or (DATA_DIR / 'f006_path_metadata.json')
        with open(path, 'r') as f:
            return json.load(f)

    def load_curation_export(self) -> dict:
        """Load curation-export.json from cache or remote."""
        if CURATION_CACHE.exists():
            with open(CURATION_CACHE, 'r') as f:
                return json.load(f)
        # Fetch from remote
        print(f'    Fetching curation-export.json from {CURATION_EXPORT_URL}...')
        resp = requests.get(CURATION_EXPORT_URL)
        resp.raise_for_status()
        data = resp.json()
        # Cache locally
        with open(CURATION_CACHE, 'w') as f:
            json.dump(data, f, indent=2)
        return data

    def _extract_metadata_parents(self, curation_data: dict) -> list:
        """Extract parent relationships from curation-export.json.

        Returns list of 3-tuples (dataset_id, child, parent).
        """
        parents = []

        # Sample to parent (subject or derived-from sample)
        for s in curation_data.get('samples', []):
            sample_id = s['sample_id']
            if 'was_derived_from' in s:
                # was_derived_from can be a list
                wdf = s['was_derived_from']
                if isinstance(wdf, list):
                    for p in wdf:
                        parents.append((DATASET_UUID, sample_id, p))
                else:
                    parents.append((DATASET_UUID, sample_id, wdf))
            else:
                parents.append((DATASET_UUID, sample_id, s['subject_id']))

        # Site to specimen
        for s in curation_data.get('sites', []):
            parents.append((DATASET_UUID, s['site_id'], s['specimen_id']))

        return parents

    def _add_curation_instances(self, instances: dict, curation_data: dict):
        """Add instances from curation export that might not be in path metadata.

        The curation export has authoritative subject/sample/site data that must exist
        for parent relationships to work. This ensures all referenced entities exist.
        """
        # Build subject lookup from curation samples
        sample_to_subject = {}
        for s in curation_data.get('samples', []):
            sample_to_subject[s['sample_id']] = s['subject_id']

        # Add subjects from curation
        for s in curation_data.get('subjects', []):
            sub_id = s['subject_id']
            if sub_id not in instances:
                instances[sub_id] = {
                    'type': 'subject',
                    'id_formal': sub_id,
                    'id_sub': sub_id,
                    'desc_inst_label': 'human',
                }

        # Add samples from curation
        for s in curation_data.get('samples', []):
            sam_id = s['sample_id']
            sub_id = s.get('subject_id')
            if sam_id not in instances:
                instances[sam_id] = {
                    'type': 'sample',
                    'id_formal': sam_id,
                    'id_sub': sub_id,
                    'id_sam': sam_id,
                    'desc_inst_label': 'nerve-volume',
                }

        # Build site -> subject lookup (store as instance variable for fiber processing)
        self.site_to_subject = {}
        self.site_to_sample = {}
        for s in curation_data.get('sites', []):
            specimen_id = s['specimen_id']
            self.site_to_sample[s['site_id']] = specimen_id if specimen_id.startswith('sam-') else None
            if specimen_id.startswith('sam-'):
                self.site_to_subject[s['site_id']] = sample_to_subject.get(specimen_id)
            elif specimen_id.startswith('sub-'):
                self.site_to_subject[s['site_id']] = specimen_id

        # Add sites from curation (with correct id_sam)
        for s in curation_data.get('sites', []):
            site_id = s['site_id']
            specimen_id = s['specimen_id']
            if site_id not in instances:
                inst_data = {
                    'type': 'site',
                    'id_formal': site_id,
                    'id_sub': self.site_to_subject.get(site_id),
                    'desc_inst_label': 'nerve-cross-section',
                }
                # Only set id_sam if specimen is a sample
                if specimen_id.startswith('sam-'):
                    inst_data['id_sam'] = specimen_id
                instances[site_id] = inst_data
            else:
                # Update existing site with id_sam if needed
                if specimen_id.startswith('sam-'):
                    instances[site_id]['id_sam'] = specimen_id

    def _build_path_to_curation_site_mapping(self, path_metadata: dict, curation_data: dict):
        """Build mapping from path-derived site IDs to curation site IDs.

        Path metadata has simplified site IDs like 'site-l-seg-c2-A-L3' while
        curation export has granular IDs like 'site-l-seg-c2-A-L3-1'.

        Strategy:
        1. Exact match first
        2. Prefix match with -th suffix handling
        3. Take first matching candidate for ambiguous cases
        """
        curation_sites = {s['site_id'] for s in curation_data.get('sites', [])}

        # Extract path sites from metadata
        path_sites = set()
        for item in path_metadata.get('data', []):
            drp = item.get('dataset_relative_path', '')
            parts = pathlib.Path(drp).parts
            for part in parts:
                if part.startswith('site-'):
                    path_sites.add(part)

        # Build mapping
        self.path_to_curation_site = {}
        for path_site in path_sites:
            # Check exact match first
            if path_site in curation_sites:
                self.path_to_curation_site[path_site] = path_site
                continue

            # Find candidates by prefix matching
            is_th = path_site.endswith('-th')
            base = path_site[:-3] if is_th else path_site

            candidates = []
            for curation_site in curation_sites:
                # Must start with base and have additional suffix
                if curation_site.startswith(base) and curation_site != path_site:
                    curation_is_th = curation_site.endswith('-th')
                    # Match -th suffix if present
                    if is_th == curation_is_th:
                        candidates.append(curation_site)

            if candidates:
                # Take the first sorted candidate for consistency
                self.path_to_curation_site[path_site] = sorted(candidates)[0]

        # Log mapping stats
        mapped = len(self.path_to_curation_site)
        unmapped = len(path_sites) - mapped
        if unmapped > 0:
            print(f'    Warning: {unmapped} path sites could not be mapped to curation sites')

    def run(self, session, commit: bool = True, csv_limit: int = None):
        """
        Run the complete ingestion pipeline.

        Parameters
        ----------
        session : sqlalchemy.orm.Session
            Database session.
        commit : bool
            Whether to commit changes (default: True).
        csv_limit : int, optional
            Limit number of CSV files to process (for testing).
        """
        # Step 1-3: Setup
        self.descriptor_ids = create_all_descriptors_from_yaml(session, self.models, self.config)
        metadata = self.load_metadata()
        curation_data = self.load_curation_export()
        dataset_obj = self._create_dataset(session)

        # Step 4: Create objects_internal entry for path-metadata provenance tracking
        self.internal_object_uuid = self._insert_objects_internal(session, dataset_obj, metadata)

        # Step 4.5: Build path-to-curation site mapping for consistent site ID resolution
        self._build_path_to_curation_site_mapping(metadata, curation_data)

        # Step 5: Base instances (path-based parents are now replaced by authoritative metadata)
        instances, _base_parents = self._extract_instances(metadata)

        # Extract authoritative parent relationships from curation-export.json
        metadata_parents = self._extract_metadata_parents(curation_data)
        print(f'    Loaded {len(metadata_parents)} parent relationships from curation-export.json')

        # Add instances from curation export (subjects, samples, sites) and set id_sam
        self._add_curation_instances(instances, curation_data)

        self._create_instances(session, instances, dataset_obj)

        # Step 5-6: Fascicle processing
        fasc_files = self._find_fascicle_csv_files(metadata)
        self._process_all_fascicle_files(session, fasc_files, dataset_obj)
        if self.pending_fascicle_instances:
            self._insert_fascicle_instances(session, dataset_obj)

        # Step 7: JPX processing
        jpx_files = self._find_jpx_files(metadata)
        if jpx_files:
            self._process_jpx_files(session, jpx_files, dataset_obj)
            if self.pending_jpx_instances:
                self._insert_jpx_instances(session, dataset_obj)

        # Step 8: Fiber CSV processing
        csv_files = self._find_csv_files(metadata)
        if csv_limit:
            csv_files = csv_files[:csv_limit]
        self._process_all_csv_files(session, csv_files, dataset_obj)

        # Step 9: Insert all instances
        self._insert_fiber_instances(session, dataset_obj)

        # Step 10: Create parent relationships
        # Convert path-based 2-tuples to 3-tuples for sorting
        path_parents_3tuple = [(DATASET_UUID, c, p) for c, p in self.parents]
        # Merge with metadata parents and deduplicate
        all_parents = set(metadata_parents + path_parents_3tuple)
        # Sort with topological ordering for sample-to-sample relationships
        sorted_parents = sort_parents(list(all_parents))
        print(f'    Creating {len(sorted_parents)} sorted parent relationships...')
        # Convert back to 2-tuples for _create_parents
        self._create_parents(session, [(c, p) for _, c, p in sorted_parents])

        # Step 11-14: Insert FK tables and values
        self._insert_obj_desc_inst(session)
        self._insert_obj_desc_quant(session)
        self._insert_values_quant(session, dataset_obj)
        self._insert_obj_desc_cat(session)
        self._insert_values_cat(session, dataset_obj)

        # Step 15: Insert dataset_object links (dataset -> packages)
        self._insert_dataset_objects(session)

        if commit:
            session.commit()

        return {
            'dataset': dataset_obj,
            'instances': len(self.instance_lookup),
            'fascicle_instances': self.fascicle_count,
            'jpx_instances': self.jpx_count,
            'fiber_instances': self.fiber_count,
            'values_quant': len(self.values_quant),
            'values_cat': len(self.values_cat),
        }

    def _create_dataset(self, session) -> Any:
        """Create the dataset object."""
        Objects = self.models.get('objects')
        if not Objects:
            raise ValueError('objects table not found in models')

        instance, _ = get_or_create_dynamic(
            session, Objects, {'id': DATASET_UUID, 'id_type': 'dataset'}, unique_keys=['id']
        )
        session.flush()
        return instance

    def _compute_updated_transitive(self, metadata: dict) -> Optional[datetime]:
        """Compute the max timestamp_updated from path metadata (excluding dataset object)."""
        timestamps = []
        for i, item in enumerate(metadata.get('data', [])):
            if i == 0:
                continue  # Skip the dataset object itself
            ts = item.get('timestamp_updated')
            if ts:
                try:
                    parsed = dateutil.parser.parse(ts.replace(',', '.'))
                    timestamps.append(parsed)
                except (ValueError, TypeError):
                    pass
        return max(timestamps) if timestamps else None

    def _insert_objects_internal(self, session, dataset_obj, metadata: dict) -> Optional[str]:
        """Insert objects_internal entry for path-metadata and corresponding quantdb object.

        Returns the internal object UUID if successful.
        """
        updated_transitive = self._compute_updated_transitive(metadata)
        if not updated_transitive:
            print('    Warning: Could not compute updated_transitive, skipping objects_internal')
            return None

        dataset_uuid = str(dataset_obj.id)
        label = f'f006-ingestion {updated_transitive.isoformat()}'

        # Insert into objects_internal with upsert pattern
        # Uses CTE to handle ON CONFLICT DO NOTHING while still returning the ID
        result = session.execute(
            sql_text(
                'WITH ins AS ('
                '  INSERT INTO objects_internal (type, dataset, updated_transitive, label) '
                "  VALUES ('path-metadata', :dataset, :updated_transitive, :label) "
                '  ON CONFLICT DO NOTHING RETURNING id'
                ') '
                'SELECT id FROM ins '
                'UNION ALL '
                'SELECT id FROM objects_internal '
                "WHERE type = 'path-metadata' AND dataset = :dataset AND updated_transitive = :updated_transitive"
            ),
            dict(
                dataset=dataset_uuid,
                updated_transitive=updated_transitive,
                label=label,
            ),
        )
        rows = list(result)
        if not rows:
            print('    Warning: Failed to get objects_internal ID')
            return None

        internal_uuid = str(rows[0][0])

        # Insert corresponding 'quantdb' type object entry
        session.execute(
            sql_text(
                'INSERT INTO objects (id, id_type, id_internal) '
                "VALUES (:id, 'quantdb', :id) "
                'ON CONFLICT DO NOTHING'
            ),
            dict(id=internal_uuid),
        )
        session.flush()

        print(f'    Created objects_internal entry: {internal_uuid[:8]}... (updated: {updated_transitive.date()})')
        return internal_uuid

    def _extract_instances(self, metadata: dict) -> tuple:
        """
        Extract instance data from path metadata.

        Returns tuple of (instances_dict, parents_list).
        """
        instances = {}
        parents = []

        for item in metadata.get('data', []):
            drp = item.get('dataset_relative_path', '')
            if not drp:
                continue

            parts = pathlib.Path(drp).parts
            parsed = self._parse_path(parts)
            if not parsed:
                continue

            # Subject
            sub_id = parsed.get('subject_id')
            if sub_id and sub_id not in instances:
                instances[sub_id] = {
                    'type': 'subject',
                    'id_formal': sub_id,
                    'id_sub': sub_id,
                    'desc_inst_label': 'human',
                }

            # Sample
            sam_id = parsed.get('sample_id')
            if sam_id and sam_id not in instances:
                instances[sam_id] = {
                    'type': 'sample',
                    'id_formal': sam_id,
                    'id_sub': sub_id,
                    'id_sam': sam_id,
                    'desc_inst_label': 'nerve-volume',
                }
                if sub_id:
                    parents.append((sam_id, sub_id))

            # Site - skip creating path-based site instances here.
            # Curation instances are authoritative and will be added by _add_curation_instances.
            # Path site IDs will be resolved to curation site IDs during fiber/fascicle processing.

        return instances, parents

    def _parse_path(self, parts: tuple) -> Optional[dict]:
        """Parse path parts to extract subject, sample, site IDs."""
        result = {}

        for part in parts:
            if part.startswith('sub-'):
                result['subject_id'] = part
            elif part.startswith('sam-'):
                result['sample_id'] = part
            elif part.startswith('site-'):
                result['site_id'] = part

        return result if result else None

    def _create_instances(self, session, instances: dict, dataset_obj):
        """Create values_inst records."""
        ValuesInst = self.models.get('values_inst')
        if not ValuesInst:
            return

        desc_inst_ids = self.descriptor_ids.get('descriptors_inst', {})

        for id_formal, inst_data in instances.items():
            desc_label = inst_data.get('desc_inst_label', 'nerve-volume')
            desc_id = desc_inst_ids.get(desc_label)

            data = {
                'dataset': str(dataset_obj.id),
                'id_formal': id_formal,
                'type': inst_data['type'],
                'desc_inst': desc_id,
                'id_sub': inst_data.get('id_sub'),
                'id_sam': inst_data.get('id_sam'),
            }

            instance, _ = get_or_create_dynamic(session, ValuesInst, data, unique_keys=['dataset', 'id_formal'])
            self.instance_lookup[id_formal] = instance.id

        session.flush()

    def _create_parents(self, session, parents: list):
        """Create instance_parent relationships using batch SQL inserts."""
        if not parents:
            return

        # Resolve formal names to IDs and filter out any with missing IDs
        resolved_parents = []
        skipped = 0
        for child_formal, parent_formal in parents:
            child_id = self.instance_lookup.get(child_formal)
            parent_id = self.instance_lookup.get(parent_formal)

            if child_id and parent_id:
                resolved_parents.append((child_id, parent_id))
            else:
                skipped += 1

        if skipped > 0:
            print(f'    Warning: Skipped {skipped} parent relationships with missing IDs')

        if not resolved_parents:
            return

        print(f'    Inserting {len(resolved_parents)} parent relationships...')

        # Use batch SQL inserts like reference implementation
        ocdn = ' ON CONFLICT DO NOTHING'
        batch_size = 10000

        for i in range(0, len(resolved_parents), batch_size):
            batch = resolved_parents[i : i + batch_size]
            values = ', '.join(f'({child_id}, {parent_id})' for child_id, parent_id in batch)
            session.execute(sql_text(f'INSERT INTO instance_parent (id, parent) VALUES {values}{ocdn}'))
            session.flush()

    def _find_csv_files(self, metadata: dict) -> list:
        """Find fiber CSV files in metadata (excluding nested fasc-* fiber files per reference)."""
        csv_items = [item for item in metadata.get('data', []) if item.get('mimetype') == 'text/csv']

        # Per reference: exclude fasc-*/*fibers.csv as redundant with merged files
        fibs = [
            p
            for p in csv_items
            if p.get('basename', '').endswith('fibers.csv') and '/fasc-' not in p.get('dataset_relative_path', '')
        ]

        return fibs

    def _find_fascicle_csv_files(self, metadata: dict) -> list:
        """Find fascicle CSV files in metadata."""
        csv_items = [item for item in metadata.get('data', []) if item.get('mimetype') == 'text/csv']

        fascs = [p for p in csv_items if p.get('basename', '').endswith('fascicles.csv')]

        return fascs

    def _find_jpx_files(self, metadata: dict) -> list:
        """Find JPX (microCT volume) files in metadata."""
        return [item for item in metadata.get('data', []) if item.get('mimetype') == 'image/jpx']

    def _process_jpx_files(self, session, jpx_files: list, dataset_obj):
        """Process JPX files to create nerve-volume instances with anatomical indices."""
        ValuesInst = self.models.get('values_inst')
        Objects = self.models.get('objects')
        if not ValuesInst or not Objects:
            return

        desc_inst_ids = self.descriptor_ids.get('descriptors_inst', {})
        nv_desc_id = desc_inst_ids.get('nerve-volume')
        if not nv_desc_id:
            return

        # Collect raw anatomical indices for all samples
        rawind = {}
        jpx_data = []

        for jpx_info in jpx_files:
            drp = jpx_info.get('dataset_relative_path', '')
            parts = pathlib.Path(drp).parts
            parsed = self._parse_path(parts)
            if not parsed:
                continue

            sam_id = parsed.get('sample_id')
            sub_id = parsed.get('subject_id')
            if not sam_id:
                continue

            # Calculate raw anatomical index
            raw_idx = anat_index(sam_id)
            rawind[(DATASET_UUID, sam_id)] = raw_idx
            jpx_data.append(
                {
                    'jpx_info': jpx_info,
                    'sam_id': sam_id,
                    'sub_id': sub_id,
                    'raw_idx': raw_idx,
                }
            )

        if not jpx_data:
            return

        # Calculate normalized indices
        sindex = proc_anat(rawind)

        # Create nerve-volume instances for unique samples
        seen_samples = set()
        for data in jpx_data:
            sam_id = data['sam_id']
            if sam_id in seen_samples:
                continue
            seen_samples.add(sam_id)

            nai, nain, naix = sindex.get((DATASET_UUID, sam_id), (0.5, 0.0, 1.0))

            # Create package object for JPX
            pkg_uuid = str(uuid_module.uuid4())
            pkg_obj, _ = get_or_create_dynamic(
                session,
                Objects,
                {'id': pkg_uuid, 'id_type': 'package', 'id_file': data['jpx_info'].get('remote_inode_id')},
                unique_keys=['id'],
            )

            # Track dataset_object relationship
            self.pending_dataset_objects.append((str(dataset_obj.id), pkg_uuid))

            # nerve-volume instance (type='below' since id_formal doesn't start with sam-)
            nv_formal = f'nv-{sam_id}'
            if nv_formal not in self.instance_lookup:
                self.instance_lookup[nv_formal] = None
                self.pending_jpx_instances.append(
                    {
                        'dataset': str(dataset_obj.id),
                        'id_formal': nv_formal,
                        'type': 'below',
                        'desc_inst': nv_desc_id,
                        'id_sub': data['sub_id'],
                        'id_sam': sam_id,
                    }
                )
                self.parents.append((nv_formal, sam_id))

            # Add quantitative values for anatomical indices (placeholder - needs desc_quant setup)
            # These would be: norm_anat_index_v2, norm_anat_index_v2_min, norm_anat_index_v2_max

        self.jpx_count = len(seen_samples)

    def _insert_jpx_instances(self, session, dataset_obj):
        """Bulk insert JPX nerve-volume instances."""
        ValuesInst = self.models.get('values_inst')
        if not ValuesInst or not self.pending_jpx_instances:
            return

        batch_size = 1000
        for i in range(0, len(self.pending_jpx_instances), batch_size):
            batch = self.pending_jpx_instances[i : i + batch_size]
            session.bulk_insert_mappings(ValuesInst, batch)
            session.flush()

    def _get_cached_csv_path(self, csv_info: dict) -> Optional[pathlib.Path]:
        """Get path to cached CSV file using remote_inode_id."""
        inode_id = csv_info.get('remote_inode_id')
        basename = csv_info.get('basename', '')

        if not inode_id or not CACHE_DIR.exists():
            return None

        # Try to find matching cached file: {inode_id}_{basename} or {inode_id}_{something}.csv
        for cached_file in CACHE_DIR.glob(f'{inode_id}_*.csv'):
            return cached_file

        return None

    def _process_all_csv_files(self, session, csv_files: list, dataset_obj):
        """Process all CSV files to create fiber instances and values."""
        ValuesInst = self.models.get('values_inst')
        Objects = self.models.get('objects')

        if not ValuesInst or not Objects:
            return

        desc_inst_ids = self.descriptor_ids.get('descriptors_inst', {})
        fiber_desc_id = desc_inst_ids.get('fiber-cross-section')

        total_files = len(csv_files)
        for file_idx, csv_info in enumerate(csv_files):
            if file_idx % 50 == 0:
                print(f'    Processing file {file_idx + 1}/{total_files}...')
                session.flush()  # Periodic flush
            cached_path = self._get_cached_csv_path(csv_info)
            if not cached_path:
                continue

            drp = csv_info.get('dataset_relative_path', '')
            parts = pathlib.Path(drp).parts
            parsed = self._parse_path(parts)
            if not parsed:
                continue

            # Determine parent instance (site or sample)
            path_site_id = parsed.get('site_id')
            sam_id = parsed.get('sample_id')
            sub_id = parsed.get('subject_id')

            # Resolve path site ID to curation site ID
            site_id = self.path_to_curation_site.get(path_site_id) if path_site_id else None

            # Check if this is a fasc-* nested file
            fasc_id = None
            for part in parts:
                if part.startswith('fasc-'):
                    fasc_id = part.split('-')[-1]
                    break

            # Base for fiber id_formal (use resolved curation site ID)
            if fasc_id:
                # Nested fiber file: parent is the fascicle
                base = site_id or sam_id
                fasc_formal = f'fasc-{base}-{fasc_id}'
                parent_formal = fasc_formal
            else:
                # Top-level fiber file: parent is site or sample
                parent_formal = site_id or sam_id

            if not parent_formal:
                continue

            # Create package object for the CSV file
            pkg_uuid = str(uuid_module.uuid4())
            pkg_obj, _ = get_or_create_dynamic(
                session,
                Objects,
                {'id': pkg_uuid, 'id_type': 'package', 'id_file': csv_info.get('remote_inode_id')},
                unique_keys=['id'],
            )

            # Track dataset_object relationship
            self.pending_dataset_objects.append((str(dataset_obj.id), pkg_uuid))

            # Collect obj_desc_inst entry for this package
            if fiber_desc_id:
                addr_ids = self.descriptor_ids.get('addresses', {})
                const_addr = addr_ids.get('record_index') or 1  # Use a default address
                self.pending_obj_desc_inst.append(
                    {
                        'object': pkg_uuid,
                        'desc_inst': fiber_desc_id,
                        'addr_field': const_addr,
                        'addr_desc_inst': None,
                    }
                )

            # Collect obj_desc_quant entries for this package (one per quant descriptor)
            desc_quant_ids = self.descriptor_ids.get('descriptors_quant', {})
            for col_name, desc_label in FIBER_QUANT_COLUMNS.items():
                desc_quant_id = desc_quant_ids.get(desc_label)
                if desc_quant_id:
                    self.pending_obj_desc_quant.add((pkg_uuid, desc_quant_id, const_addr))

            # Collect obj_desc_cat entries for this package (one per cat descriptor)
            desc_cat_ids = self.descriptor_ids.get('descriptors_cat', {})
            axon_desc_cat = desc_cat_ids.get('hasAxonFiberType')
            # If not in YAML, look up from database (cached after first lookup)
            if axon_desc_cat is None and not hasattr(self, '_axon_desc_cat_id'):
                from sqlalchemy import text

                result = session.execute(
                    text("SELECT id FROM descriptors_cat WHERE label = 'hasAxonFiberType' LIMIT 1")
                ).fetchone()
                self._axon_desc_cat_id = result[0] if result else None
            if axon_desc_cat is None:
                axon_desc_cat = getattr(self, '_axon_desc_cat_id', None)
            if axon_desc_cat:
                self.pending_obj_desc_cat.add((pkg_uuid, axon_desc_cat, const_addr))

            # Process CSV rows
            self._process_fiber_csv(
                session,
                cached_path,
                dataset_obj,
                pkg_uuid,
                parent_formal,
                sub_id,
                sam_id,
                fiber_desc_id,
                fasc_id,
            )

        session.flush()

    def _process_fiber_csv(
        self,
        session,
        csv_path: pathlib.Path,
        dataset_obj,
        pkg_uuid: str,
        parent_formal: str,
        sub_id: str,
        sam_id: str,
        fiber_desc_id: int,
        fasc_id: Optional[str],
    ):
        """Process a single fiber CSV file - collects data for bulk insert."""
        desc_quant_ids = self.descriptor_ids.get('descriptors_quant', {})
        cterm_ids = self.descriptor_ids.get('controlled_terms', {})

        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            print(f'    Error reading {csv_path}: {e}')
            return

        for idx, row in enumerate(rows):
            # Create fiber instance id_formal
            fiber_num = idx + 1
            if fasc_id:
                fiber_formal = f'fiber-fasc-{parent_formal.replace("fasc-", "")}-{fiber_num}'
            else:
                fiber_formal = f'fiber-{parent_formal}-{fiber_num}'

            # Skip if already seen
            if fiber_formal in self.instance_lookup:
                continue

            # Mark as seen (will assign real ID after bulk insert)
            self.instance_lookup[fiber_formal] = None
            self.fiber_count += 1

            # Collect fiber instance for bulk insert
            # Look up correct id_sub from site's curation data, fallback to path-parsed sub_id
            site_formal = parent_formal if parent_formal.startswith('site-') else None
            fiber_id_sub = self.site_to_subject.get(site_formal) if site_formal else None
            if not fiber_id_sub:
                fiber_id_sub = sub_id  # Fallback to path-parsed subject

            fiber_data = {
                'dataset': str(dataset_obj.id),
                'id_formal': fiber_formal,
                'type': 'below',
                'desc_inst': fiber_desc_id,
                'id_sub': fiber_id_sub,
                # id_sam not set - derived from parent hierarchy (site -> sample)
            }
            self.pending_fiber_instances.append(fiber_data)

            # Add parent relationship (will resolve IDs later)
            self.parents.append((fiber_formal, parent_formal))

            # Collect quantitative values (will resolve instance ID later)
            for col_name, desc_label in FIBER_QUANT_COLUMNS.items():
                if col_name in row and row[col_name]:
                    try:
                        value = float(row[col_name])
                        desc_quant_id = desc_quant_ids.get(desc_label)
                        if desc_quant_id:
                            self.values_quant.append(
                                {
                                    'value': value,
                                    'object': pkg_uuid,
                                    'desc_inst': fiber_desc_id,
                                    'desc_quant': desc_quant_id,
                                    'instance_formal': fiber_formal,  # Will resolve to ID later
                                    'value_blob': json.dumps({'raw': row[col_name]}),
                                }
                            )
                    except (ValueError, TypeError):
                        pass

            # Collect categorical values (myelinated)
            for col_name, (true_val, false_val) in FIBER_CAT_COLUMNS.items():
                if col_name in row:
                    is_true = row[col_name].lower() == 'true'
                    term_label = true_val if is_true else false_val
                    term_id = cterm_ids.get(term_label)
                    if term_id:
                        self.values_cat.append(
                            {
                                'value_open': term_label,
                                'value_controlled': term_id,
                                'object': pkg_uuid,
                                'desc_inst': fiber_desc_id,
                                'instance_formal': fiber_formal,  # Will resolve to ID later
                            }
                        )

    def _process_all_fascicle_files(self, session, fasc_files: list, dataset_obj):
        """Process all fascicle CSV files to create fascicle instances and values."""
        ValuesInst = self.models.get('values_inst')
        Objects = self.models.get('objects')

        if not ValuesInst or not Objects:
            return

        desc_inst_ids = self.descriptor_ids.get('descriptors_inst', {})
        fasc_desc_id = desc_inst_ids.get('fascicle-cross-section')

        if not fasc_desc_id:
            print('    Warning: fascicle-cross-section descriptor not found, skipping fascicles')
            return

        total_files = len(fasc_files)
        processed = 0
        for file_idx, csv_info in enumerate(fasc_files):
            if file_idx % 10 == 0:
                print(f'    Processing fascicle file {file_idx + 1}/{total_files}...')
                session.flush()

            cached_path = self._get_cached_csv_path(csv_info)
            if not cached_path:
                continue

            processed += 1
            drp = csv_info.get('dataset_relative_path', '')
            parts = pathlib.Path(drp).parts
            parsed = self._parse_path(parts)
            if not parsed:
                continue

            path_site_id = parsed.get('site_id')
            sam_id = parsed.get('sample_id')
            sub_id = parsed.get('subject_id')

            # Resolve path site ID to curation site ID
            site_id = self.path_to_curation_site.get(path_site_id) if path_site_id else None

            # Parent is site if available, otherwise sample
            parent_formal = site_id or sam_id
            if not parent_formal:
                continue

            # Create package object for the CSV file
            pkg_uuid = str(uuid_module.uuid4())
            pkg_obj, _ = get_or_create_dynamic(
                session,
                Objects,
                {'id': pkg_uuid, 'id_type': 'package', 'id_file': csv_info.get('remote_inode_id')},
                unique_keys=['id'],
            )

            # Track dataset_object relationship
            self.pending_dataset_objects.append((str(dataset_obj.id), pkg_uuid))

            # Collect obj_desc_inst entry for this package
            addr_ids = self.descriptor_ids.get('addresses', {})
            fascicle_addr = addr_ids.get('fascicle') or 1
            self.pending_obj_desc_inst.append(
                {
                    'object': pkg_uuid,
                    'desc_inst': fasc_desc_id,
                    'addr_field': fascicle_addr,
                    'addr_desc_inst': None,
                }
            )

            # Collect obj_desc_quant entries for fascicle measurements
            desc_quant_ids = self.descriptor_ids.get('descriptors_quant', {})
            for col_name, desc_label in FASCICLE_QUANT_COLUMNS.items():
                desc_quant_id = desc_quant_ids.get(desc_label)
                if desc_quant_id:
                    self.pending_obj_desc_quant.add((pkg_uuid, desc_quant_id, fascicle_addr))

            # Process CSV rows
            self._process_fascicle_csv(
                session,
                cached_path,
                dataset_obj,
                pkg_uuid,
                parent_formal,
                sub_id,
                sam_id,
                fasc_desc_id,
            )

        if processed == 0:
            print('    No cached fascicle files found (fascicle CSVs need to be downloaded)')
        session.flush()

    def _process_fascicle_csv(
        self,
        session,
        csv_path: pathlib.Path,
        dataset_obj,
        pkg_uuid: str,
        parent_formal: str,
        sub_id: str,
        sam_id: str,
        fasc_desc_id: int,
    ):
        """Process a single fascicle CSV file - collects data for bulk insert."""
        desc_quant_ids = self.descriptor_ids.get('descriptors_quant', {})

        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            print(f'    Error reading {csv_path}: {e}')
            return

        for idx, row in enumerate(rows):
            # Get fascicle ID from the 'fascicle' column
            fasc_num = row.get('fascicle', str(idx + 1))
            fasc_formal = f'fasc-{parent_formal}-{fasc_num}'

            # Skip if already seen
            if fasc_formal in self.instance_lookup:
                continue

            # Mark as seen (will assign real ID after bulk insert)
            self.instance_lookup[fasc_formal] = None
            self.fascicle_count += 1

            # Collect fascicle instance for bulk insert
            # Look up correct id_sub from site's curation data, fallback to path-parsed sub_id
            site_formal = parent_formal if parent_formal.startswith('site-') else None
            fasc_id_sub = self.site_to_subject.get(site_formal) if site_formal else None
            if not fasc_id_sub:
                fasc_id_sub = sub_id  # Fallback to path-parsed subject

            fasc_data = {
                'dataset': str(dataset_obj.id),
                'id_formal': fasc_formal,
                'type': 'below',
                'desc_inst': fasc_desc_id,
                'id_sub': fasc_id_sub,
                # id_sam not set - derived from parent hierarchy (site -> sample)
            }
            self.pending_fascicle_instances.append(fasc_data)

            # Add parent relationship
            self.parents.append((fasc_formal, parent_formal))

            # Collect quantitative values
            for col_name, desc_label in FASCICLE_QUANT_COLUMNS.items():
                if col_name in row and row[col_name]:
                    try:
                        value = float(row[col_name])
                        desc_quant_id = desc_quant_ids.get(desc_label)
                        if desc_quant_id:
                            self.values_quant.append(
                                {
                                    'value': value,
                                    'object': pkg_uuid,
                                    'desc_inst': fasc_desc_id,
                                    'desc_quant': desc_quant_id,
                                    'instance_formal': fasc_formal,
                                    'value_blob': json.dumps({'raw': row[col_name]}),
                                }
                            )
                    except (ValueError, TypeError):
                        pass

    def _insert_fascicle_instances(self, session, dataset_obj):
        """Bulk insert fascicle instances."""
        ValuesInst = self.models.get('values_inst')
        if not ValuesInst or not self.pending_fascicle_instances:
            return

        print(f'    Inserting {len(self.pending_fascicle_instances)} fascicle instances...')

        batch_size = 10000
        for i in range(0, len(self.pending_fascicle_instances), batch_size):
            batch = self.pending_fascicle_instances[i : i + batch_size]
            session.bulk_insert_mappings(ValuesInst, batch)
            session.flush()

    def _insert_fiber_instances(self, session, dataset_obj):
        """Bulk insert fiber instances and update instance_lookup with real IDs."""
        ValuesInst = self.models.get('values_inst')
        if not ValuesInst or not self.pending_fiber_instances:
            return

        print(f'    Inserting {len(self.pending_fiber_instances)} fiber instances...')

        # Bulk insert
        batch_size = 10000
        for i in range(0, len(self.pending_fiber_instances), batch_size):
            batch = self.pending_fiber_instances[i : i + batch_size]
            session.bulk_insert_mappings(ValuesInst, batch)
            session.flush()

        # Now query back to get the actual IDs
        print('    Resolving instance IDs...')
        from sqlalchemy import select

        dataset_id = str(dataset_obj.id)

        # Query all instances for this dataset
        stmt = select(ValuesInst).where(ValuesInst.dataset == dataset_id)
        results = session.execute(stmt).scalars().all()

        for inst in results:
            self.instance_lookup[inst.id_formal] = inst.id

        print(f'    Resolved {len([v for v in self.instance_lookup.values() if v])} instance IDs')

    def _insert_obj_desc_inst(self, session):
        """Insert obj_desc_inst entries to satisfy FK constraints."""
        ObjDescInst = self.models.get('obj_desc_inst')
        if not ObjDescInst or not self.pending_obj_desc_inst:
            return

        print(f'    Inserting {len(self.pending_obj_desc_inst)} obj_desc_inst entries...')

        # Bulk insert
        batch_size = 10000
        for i in range(0, len(self.pending_obj_desc_inst), batch_size):
            batch = self.pending_obj_desc_inst[i : i + batch_size]
            session.bulk_insert_mappings(ObjDescInst, batch)
            session.flush()

    def _insert_obj_desc_quant(self, session):
        """Insert obj_desc_quant entries to satisfy FK constraints for values_quant."""
        ObjDescQuant = self.models.get('obj_desc_quant')
        if not ObjDescQuant or not self.pending_obj_desc_quant:
            return

        print(f'    Inserting {len(self.pending_obj_desc_quant)} obj_desc_quant entries...')

        # Convert set of tuples to list of dicts
        entries = [
            {'object': obj, 'desc_quant': dq, 'addr_field': addr} for obj, dq, addr in self.pending_obj_desc_quant
        ]

        # Bulk insert
        batch_size = 10000
        for i in range(0, len(entries), batch_size):
            batch = entries[i : i + batch_size]
            session.bulk_insert_mappings(ObjDescQuant, batch)
            session.flush()

    def _insert_obj_desc_cat(self, session):
        """Insert obj_desc_cat entries to satisfy FK constraints for values_cat."""
        ObjDescCat = self.models.get('obj_desc_cat')
        if not ObjDescCat or not self.pending_obj_desc_cat:
            return

        print(f'    Inserting {len(self.pending_obj_desc_cat)} obj_desc_cat entries...')

        # Convert set of tuples to list of dicts
        entries = [{'object': obj, 'desc_cat': dc, 'addr_field': addr} for obj, dc, addr in self.pending_obj_desc_cat]

        # Bulk insert
        batch_size = 10000
        for i in range(0, len(entries), batch_size):
            batch = entries[i : i + batch_size]
            session.bulk_insert_mappings(ObjDescCat, batch)
            session.flush()

    def _insert_dataset_objects(self, session):
        """Insert dataset_object entries linking dataset to packages."""
        if not self.pending_dataset_objects:
            return

        # Deduplicate
        unique_pairs = list(set(self.pending_dataset_objects))
        print(f'    Inserting {len(unique_pairs)} dataset_object entries...')

        # Use raw SQL for bulk insert (consistent with reference pattern)
        from sqlalchemy import text

        ocdn = ' ON CONFLICT DO NOTHING'
        batch_size = 10000

        for i in range(0, len(unique_pairs), batch_size):
            batch = unique_pairs[i : i + batch_size]
            values = ', '.join(f"('{d}', '{o}')" for d, o in batch)
            session.execute(text(f'INSERT INTO dataset_object (dataset, object) VALUES {values}{ocdn}'))
            session.flush()

    def _insert_values_quant(self, session, dataset_obj):
        """Insert collected quantitative values using bulk insert."""
        ValuesQuant = self.models.get('values_quant')
        if not ValuesQuant or not self.values_quant:
            return

        print(f'    Inserting {len(self.values_quant)} quantitative values...')

        # Resolve instance_formal to actual instance IDs
        resolved_values = []
        for vq in self.values_quant:
            inst_formal = vq.pop('instance_formal', None)
            if inst_formal:
                inst_id = self.instance_lookup.get(inst_formal)
                if inst_id:
                    vq['instance'] = inst_id
                    resolved_values.append(vq)
            elif 'instance' in vq:
                resolved_values.append(vq)

        print(f'    Resolved {len(resolved_values)} values with instance IDs')

        # Use bulk insert for much better performance
        batch_size = 10000
        for i in range(0, len(resolved_values), batch_size):
            batch = resolved_values[i : i + batch_size]
            session.bulk_insert_mappings(ValuesQuant, batch)
            session.flush()
            if (i // batch_size) % 5 == 0:
                print(f'      Inserted {min(i + batch_size, len(resolved_values))}/{len(resolved_values)} values...')

    def _insert_values_cat(self, session, dataset_obj):
        """Insert collected categorical values using bulk insert."""
        ValuesCat = self.models.get('values_cat')
        if not ValuesCat or not self.values_cat:
            return

        print(f'    Inserting {len(self.values_cat)} categorical values...')

        # Need desc_cat - look up from database since hasAxonFiberType is in SQL inserts, not YAML
        desc_cat_ids = self.descriptor_ids.get('descriptors_cat', {})
        axon_desc_cat = desc_cat_ids.get('hasAxonFiberType')

        # If not found in YAML-created descriptors, look up from database
        if axon_desc_cat is None:
            from sqlalchemy import text

            result = session.execute(
                text("SELECT id FROM descriptors_cat WHERE label = 'hasAxonFiberType' LIMIT 1")
            ).fetchone()
            if result:
                axon_desc_cat = result[0]
            else:
                print('    Warning: hasAxonFiberType descriptor not found, skipping categorical values')
                return

        # Resolve instance_formal to actual instance IDs and add desc_cat
        resolved_values = []
        for vc in self.values_cat:
            vc['desc_cat'] = axon_desc_cat
            inst_formal = vc.pop('instance_formal', None)
            if inst_formal:
                inst_id = self.instance_lookup.get(inst_formal)
                if inst_id:
                    vc['instance'] = inst_id
                    resolved_values.append(vc)
            elif 'instance' in vc:
                resolved_values.append(vc)

        print(f'    Resolved {len(resolved_values)} categorical values with instance IDs')

        # Bulk insert
        batch_size = 10000
        for i in range(0, len(resolved_values), batch_size):
            batch = resolved_values[i : i + batch_size]
            session.bulk_insert_mappings(ValuesCat, batch)
            session.flush()


def run_f006_ingestion(test: bool = True, commit: bool = True, csv_limit: int = None):
    """
    Convenience function to run F006 ingestion.

    Parameters
    ----------
    test : bool
        Use test database (default: True).
    commit : bool
        Commit changes (default: True).
    csv_limit : int, optional
        Limit CSV files processed.
    """
    session, models = get_automap_session(test=test)

    try:
        ingestion = F006Ingestion(models)
        result = ingestion.run(session, commit=commit, csv_limit=csv_limit)
        print(f'\n=== Ingestion Complete ===')
        print(f'Base instances created: {result["instances"]}')
        print(f'Fiber instances created: {result.get("fiber_instances", 0)}')
        print(f'Quantitative values created: {result.get("values_quant", 0)}')
        print(f'Categorical values created: {result.get("values_cat", 0)}')
        return result
    except Exception as e:
        session.rollback()
        print(f'Error: {e}')
        raise
    finally:
        session.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='F006 Dataset Ingestion')
    parser.add_argument('--test', action='store_true', default=True, help='Use test database (default)')
    parser.add_argument('--prod', action='store_true', help='Use production database')
    parser.add_argument('--dry-run', action='store_true', help='Do not commit changes')
    parser.add_argument('--csv-limit', type=int, help='Limit number of CSV files to process')
    args = parser.parse_args()

    run_f006_ingestion(test=not args.prod, commit=not args.dry_run, csv_limit=args.csv_limit)
