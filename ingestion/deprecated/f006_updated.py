#!/usr/bin/env python3
"""
DEPRECATED: This file is deprecated. Use ingestion/f006_ingest.py instead.

F006 Dataset Ingestion following the new ingest.py pattern

This script implements F006-specific logic using the value-generating function pattern
from the main ingest.py module.

Dataset ID: 2a3d01c0-39d3-464a-8746-54c9d67ebe0f

NOTE: The new f006_ingest.py uses automap_base for dynamic model reflection.
"""
import warnings

warnings.warn(
    'ingestion/f006_updated.py is deprecated. Use ingestion/f006_ingest.py instead.', DeprecationWarning, stacklevel=2
)

import csv
import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from sparcur.utils import PennsieveId as RemoteId

from quantdb.ingest import (
    InternalIds,
    Queries,
    ingest,
    values_objects_from_objects,
)
from quantdb.utils import isoformat, log

from .utils import (
    download_csv_from_pennsieve,
    extract_numeric_value,
    load_yaml_mappings,
    normalize_column_name,
    read_csv_with_fallback,
)

# Dataset configuration
DATASET_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'
DATA_DIR = pathlib.Path(__file__).parent / 'data'
CACHE_DIR = DATA_DIR / 'csv_cache' / DATASET_UUID


def extract_f006(dataset_uuid, source_local=True, visualize=False):
    """
    Extract F006 dataset following the new ingest.py pattern.

    Returns a tuple of value-generating functions that will be used by the ingest function.
    """
    dataset_id = RemoteId('dataset:' + dataset_uuid)

    # Load metadata
    metadata_path = DATA_DIR / 'f006_path_metadata.json'
    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
    else:
        # Download from remote if needed
        if not source_local:
            resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/LATEST/path-metadata.json')
            metadata = resp.json()
        else:
            raise FileNotFoundError(f'Metadata file not found: {metadata_path}')

    # Load mappings
    mappings_file = pathlib.Path(__file__).parent / 'f006_interlex_mappings.yaml'
    mappings = load_yaml_mappings(str(mappings_file))

    # Process files and build instance/parent structures
    instances = {}
    parents = []
    objects = {}

    # Process CSV files to extract structure
    nerve_qvs = []
    fasc_qvs = []
    fiber_qvs = []

    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Process each file in metadata
    for file_info in metadata.get('data', []):
        path = file_info.get('dataset_relative_path', '')
        if not path.endswith('.csv'):
            continue

        # Parse path structure
        path_parts = path.split('/')
        path_data = parse_f006_path_structure(path_parts)

        if not path_data.get('subject_id'):
            continue

        # Create subject and sample instances
        id_sub = path_data['subject_id']
        id_sam = path_data.get('sample_id', f'sam-{id_sub}')

        # Add to instances if not already present
        if (dataset_id, id_sub) not in instances:
            instances[(dataset_id, id_sub)] = {
                'type': 'subject',
                'desc_inst': 'subject',
                'id_sub': id_sub,
                'id_sam': None,
            }

        if (dataset_id, id_sam) not in instances:
            instances[(dataset_id, id_sam)] = {
                'type': 'sample',
                'desc_inst': 'nerve-cross-section',
                'id_sub': id_sub,
                'id_sam': id_sam,
            }
            parents.append((dataset_id, id_sam, id_sub))

        # Add file object
        if 'remote_id' in file_info:
            obj_uuid = file_info['remote_id'].split(':')[-1]
            obj_file_id = file_info.get('file_id')
            objects[obj_uuid] = {'id_type': 'package', 'id_file': obj_file_id}

        # Process CSV data if it's a fiber or fascicle file
        if 'fibers' in path or 'fascicles' in path:
            csv_path = CACHE_DIR / path_parts[-1]

            # Download if needed
            if not csv_path.exists() and not source_local:
                download_csv_from_pennsieve(dataset_uuid, path, csv_path)

            if csv_path.exists():
                df = read_csv_with_fallback(csv_path)

                if 'fascicles' in path:
                    # Process fascicle data
                    for idx, row in df.iterrows():
                        fascicle_id = row.get('fascicle', idx)
                        id_formal = f'fasc-{id_sam}-{fascicle_id}'

                        instances[(dataset_id, id_formal)] = {
                            'type': 'site',
                            'desc_inst': 'fascicle-cross-section',
                            'id_sub': id_sub,
                            'id_sam': id_sam,
                        }
                        parents.append((dataset_id, id_formal, id_sam))

                        # Collect quantitative values
                        fasc_qv = {
                            'id_formal': id_formal,
                            'desc_inst': 'fascicle-cross-section',
                        }

                        # Map columns to descriptors
                        if 'area' in row:
                            fasc_qv['area-um2'] = extract_numeric_value(row['area'])
                        if 'eff_diam' in row:
                            fasc_qv['diameter-um'] = extract_numeric_value(row['eff_diam'])

                        fasc_qvs.append(fasc_qv)

                elif 'fibers' in path:
                    # Process fiber data
                    for idx, row in df.iterrows():
                        fiber_id = idx
                        fascicle_id = row.get('fascicle')

                        if pd.notna(fascicle_id):
                            id_formal = f'fiber-{id_sam}-{fiber_id}'
                            fasc_formal = f'fasc-{id_sam}-{fascicle_id}'

                            instances[(dataset_id, id_formal)] = {
                                'type': 'instance',
                                'desc_inst': 'fiber-cross-section',
                                'id_sub': id_sub,
                                'id_sam': id_sam,
                            }

                            # Fiber is child of fascicle
                            if (dataset_id, fasc_formal) in instances:
                                parents.append((dataset_id, id_formal, fasc_formal))

                            # Collect quantitative values
                            fiber_qv = {
                                'id_formal': id_formal,
                                'desc_inst': 'fiber-cross-section',
                            }

                            if 'fiber_area' in row:
                                fiber_qv['area-um2'] = extract_numeric_value(row['fiber_area'])
                            if 'eff_fib_diam' in row:
                                fiber_qv['diameter-um'] = extract_numeric_value(row['eff_fib_diam'])

                            fiber_qvs.append(fiber_qv)

    # Sort parents for proper toposort ordering
    from quantdb.ingest import sort_parents

    parents = sort_parents(parents)

    updated_transitive = None  # Not using transitive updates for now

    values_objects = values_objects_from_objects(objects)
    values_dataset_object = [(dataset_uuid, obj_uuid) for obj_uuid in objects.keys()]

    # Define value-generating functions
    def make_values_instances(i):
        """Generate values for instances table."""
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
        """Generate values for instance_parent table."""
        values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        """Generate values for obj_desc_inst table."""
        void = []
        # Add descriptor-object mappings for CSV files
        for o, b in objects.items():
            if b['id_type'] == 'package':
                # Map to appropriate descriptors based on file content
                # This would need proper address field mapping
                void.append((o, i.id_fascicle_cross_section, None, None))
                void.append((o, i.id_fiber_cross_section, None, None))
        return void

    def make_vocd(this_dataset_updated_uuid, i):
        """Generate values for obj_desc_cat table."""
        return []  # F006 doesn't use categorical descriptors currently

    def make_voqd(this_dataset_updated_uuid, i):
        """Generate values for obj_desc_quant table."""
        voqd = []
        # Map quantitative descriptors to objects
        for o, b in objects.items():
            if b['id_type'] == 'package':
                # Add quantitative descriptor mappings
                voqd.append((o, i.reg_qd('fascicle cross section area um2'), None))
                voqd.append((o, i.reg_qd('fiber cross section area um2'), None))
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        """Generate categorical values."""
        values_cv = []
        # F006 doesn't have categorical values in the current implementation
        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        """Generate quantitative values."""
        values_qv = []

        # Process nerve quantitative values
        for nqv in nerve_qvs:
            id_formal = nqv['id_formal']
            if (dataset_id.uuid, id_formal) in luinst:
                instance_id = luinst[dataset_id.uuid, id_formal]

                if 'diameter-um' in nqv:
                    values_qv.append(
                        (
                            nqv['diameter-um'],
                            None,  # object
                            instance_id,
                            i.reg_qd('nerve cross section diameter um'),
                            instance_id,
                            None,  # value_blob
                        )
                    )

        # Process fascicle quantitative values
        for fqv in fasc_qvs:
            id_formal = fqv['id_formal']
            if (dataset_id.uuid, id_formal) in luinst:
                instance_id = luinst[dataset_id.uuid, id_formal]

                if 'area-um2' in fqv:
                    values_qv.append(
                        (
                            fqv['area-um2'],
                            None,
                            instance_id,
                            i.reg_qd('fascicle cross section area um2'),
                            instance_id,
                            None,
                        )
                    )

                if 'diameter-um' in fqv:
                    values_qv.append(
                        (
                            fqv['diameter-um'],
                            None,
                            instance_id,
                            i.reg_qd('fascicle cross section diameter um'),
                            instance_id,
                            None,
                        )
                    )

        # Process fiber quantitative values
        for fqv in fiber_qvs:
            id_formal = fqv['id_formal']
            if (dataset_id.uuid, id_formal) in luinst:
                instance_id = luinst[dataset_id.uuid, id_formal]

                if 'area-um2' in fqv:
                    values_qv.append(
                        (
                            fqv['area-um2'],
                            None,
                            instance_id,
                            i.reg_qd('fiber cross section area um2'),
                            instance_id,
                            None,
                        )
                    )

                if 'diameter-um' in fqv:
                    values_qv.append(
                        (
                            fqv['diameter-um'],
                            None,
                            instance_id,
                            i.reg_qd('fiber cross section diameter um'),
                            instance_id,
                            None,
                        )
                    )

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


def parse_f006_path_structure(path_parts: List[str]) -> Dict[str, Any]:
    """
    Parse F006-specific path structure.

    F006 has structure like:
    - sub-{species}###-{sex}###/sam-{sample}[sidedness]/
    - derivatives/sub-{species}###-{sex}###/sam-{sample}[sidedness]/

    Returns:
        Dictionary with subject_id, sample_id, sidedness, etc.
    """
    result = {}

    # Join parts to get full path for pattern matching
    full_path = '/'.join(path_parts)

    # Extract subject information
    sub_match = re.search(r'sub-(\w+)(\d+)-(\w+)(\d+)', full_path)
    if sub_match:
        species = sub_match.group(1)
        species_num = sub_match.group(2)
        sex = sub_match.group(3)
        sex_num = sub_match.group(4)
        result['subject_id'] = f'sub-{species}{species_num}-{sex}{sex_num}'
        result['species'] = species
        result['sex'] = sex

    # Extract sample information
    sam_match = re.search(r'sam-(\w+)([lr]?)', full_path)
    if sam_match:
        sample_name = sam_match.group(1)
        sidedness = sam_match.group(2)
        result['sample_id'] = f'sam-{sample_name}{sidedness}'
        result['sample_type'] = 'nerve-volume'
        if sidedness:
            result['sidedness'] = 'left' if sidedness == 'l' else 'right'

    # Check if it's derivatives
    if 'derivatives' in path_parts:
        result['is_derivative'] = True

    # Extract file type information
    if path_parts and path_parts[-1].endswith('.csv'):
        filename = path_parts[-1]
        if 'fascicles' in filename:
            result['data_type'] = 'fascicle'
        elif 'fibers' in filename:
            result['data_type'] = 'fiber'

    return result


def ingest_f006(session, source_local=True, do_insert=True, commit=False, dev=False):
    """Ingest F006 dataset using the new pattern."""
    return ingest(DATASET_UUID, extract_f006, session, commit=commit, dev=dev, source_local=source_local)


if __name__ == '__main__':
    from quantdb.client import get_session

    # Use test database by default
    session = get_session(test=True)

    try:
        ingest_f006(session, source_local=True, commit=False, dev=True)
        print('F006 ingestion completed successfully')
    except Exception as e:
        print(f'Error during ingestion: {e}')
        session.rollback()
    finally:
        session.close()
