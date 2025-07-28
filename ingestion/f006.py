#!/usr/bin/env python3
"""
F006 Dataset Ingestion using Generic Ingest Approach with CSV Data

This script demonstrates a simplified ingestion process using the ORM models
and generic_ingest helper functions, now with actual CSV data from Pennsieve.

Dataset ID: 2a3d01c0-39d3-464a-8746-54c9d67ebe0f
"""

import ast
import csv
import json
import pathlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from quantdb.client import get_session
from quantdb.generic_ingest import get_or_create
from quantdb.ingest import InternalIds, Queries
from quantdb.models import (
    Addresses,
    Aspects,
    ControlledTerms,
    DescriptorsCat,
    DescriptorsInst,
    DescriptorsQuant,
    ObjDescCat,
    ObjDescInst,
    ObjDescQuant,
    Objects,
    Units,
    ValuesCat,
    ValuesInst,
    ValuesQuant,
)
from quantdb.pennsieve_client import PennsieveClient

# Dataset configuration
DATASET_UUID = uuid.UUID('2a3d01c0-39d3-464a-8746-54c9d67ebe0f')
DATA_DIR = pathlib.Path(__file__).parent / 'data'
CACHE_DIR = DATA_DIR / 'csv_cache' / str(DATASET_UUID)


def load_path_metadata():
    """Load the path metadata from local JSON file."""
    metadata_file = DATA_DIR / 'f006_path_metadata.json'
    with open(metadata_file, 'r') as f:
        return json.load(f)


def ensure_cache_dir():
    """Ensure the cache directory exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def get_cached_csv_path(file_id: str, filename: str) -> pathlib.Path:
    """Get the path for a cached CSV file."""
    return CACHE_DIR / f'{file_id}_{filename}'


def download_csv_from_pennsieve(client: PennsieveClient, file_info: Dict[str, Any]) -> Optional[pathlib.Path]:
    """Download a CSV file from Pennsieve with caching.

    Args:
        client: PennsieveClient instance
        file_info: File metadata dictionary

    Returns:
        Path to the downloaded CSV file, or None if download failed
    """
    ensure_cache_dir()

    # Extract file info
    file_id = file_info.get('remote_inode_id', '')
    filename = file_info.get('name', pathlib.Path(file_info.get('dataset_relative_path', '')).name)
    cached_path = get_cached_csv_path(file_id, filename)

    # Check if file is already cached
    if cached_path.exists():
        print(f'Using cached file: {cached_path}')
        return cached_path

    try:
        # First try using the API URL if available
        api_url = file_info.get('uri_api')
        if api_url:
            try:
                # Use the client's private method to get the download URL
                response = client._PennsieveClient__get(api_url)
                download_data = response.json()
                download_url = download_data.get('url')

                if download_url:
                    # Download the file
                    print(f'Downloading {filename} to cache...')
                    import requests

                    actual_response = requests.get(download_url)
                    actual_response.raise_for_status()

                    # Save to cache
                    with open(cached_path, 'wb') as f:
                        f.write(actual_response.content)

                    print(f'Downloaded and cached: {cached_path} ({cached_path.stat().st_size:,} bytes)')
                    return cached_path
            except Exception as e:
                print(f'API URL method failed: {e}, trying manifest method...')

        # Fall back to manifest method using package ID
        remote_id = file_info.get('remote_id', '')
        if remote_id.startswith('package:'):
            package_id = remote_id.split(':', 1)[1]
        else:
            package_id = remote_id

        manifest = client.get_child_manifest(package_id)
        if not manifest or 'data' not in manifest or not manifest['data']:
            print(f'No manifest data for package {package_id}')
            return None

        # Find the specific file in the manifest
        file_data = None
        for item in manifest['data']:
            if str(item.get('id')) == str(file_id) or str(item.get('nodeId')) == str(file_id):
                file_data = item
                break

        if not file_data and len(manifest['data']) > 0:
            file_data = manifest['data'][0]

        if not file_data:
            print(f'File {file_id} not found in manifest')
            return None

        download_url = file_data.get('url')
        if not download_url:
            print(f'No download URL in manifest')
            return None

        # Download the file
        print(f'Downloading {filename} to cache...')
        import requests

        response = requests.get(download_url, stream=True)
        response.raise_for_status()

        # Save to cache
        with open(cached_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f'Downloaded and cached: {cached_path}')
        return cached_path

    except Exception as e:
        print(f'Error downloading file {file_id}: {e}')
        return None


def read_csv_data(csv_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Read CSV file and return data as list of dictionaries."""
    data = []
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data
    except Exception as e:
        print(f'Error reading CSV {csv_path}: {e}')
        return []


def parse_csv_path_structure(path_parts):
    """
    Parse CSV file path structure to extract subject, sample, site, fascicle info.
    Example path: derivative/sub-f006/sam-l/site-l-seg-c2-A-L3/fasc-3/3_fibers.csv
    """
    if len(path_parts) >= 5 and path_parts[0] == 'derivative':
        subject_id = path_parts[1]  # sub-f006
        sample_folder = path_parts[2]   # sam-l or sam-r
        site_id = path_parts[3]     # site-l-seg-c2-A-L3
        fasc_id = path_parts[4] if len(path_parts) > 4 else None     # fasc-3
        filename = path_parts[5] if len(path_parts) > 5 else ''  # 3_fibers.csv

        # Extract segment from site_id to construct full sample_id
        # site-l-seg-c2-A-L3 -> extract seg-c2 -> construct sam-l-seg-c2
        sample_id = sample_folder  # Default to just the folder name
        if site_id and 'seg-' in site_id:
            # Extract the segment part (e.g., 'c2' from 'site-l-seg-c2-A-L3')
            seg_parts = site_id.split('seg-')
            if len(seg_parts) > 1:
                # Get the segment identifier (e.g., 'c2' from 'c2-A-L3')
                segment = seg_parts[1].split('-')[0]
                # Construct the full sample_id to match JPX pattern
                sample_id = f'{sample_folder}-seg-{segment}'

        # Extract fascicle number from fasc_id
        fasc_num = fasc_id.split('-')[-1] if fasc_id and 'fasc-' in fasc_id else None

        return {
            'subject_id': subject_id,
            'sample_id': sample_id,
            'sample_folder': sample_folder,
            'site_id': site_id,
            'fascicle_id': fasc_id,
            'fascicle_num': fasc_num,
            'filename': filename,
            'modality': 'fiber-analysis',  # CSV files contain fiber analysis data
        }
    else:
        # Return None for CSV files we don't want to process
        return None


def parse_path_structure(path_parts):
    """
    Parse the path structure to extract subject, sample, and modality info.
    Example path: primary/sub-f006/sam-l/sam-l-seg-t5/B824_T5L_9um_2.jpx
    """
    if len(path_parts) >= 4:
        # Skip 'primary' if it's the first part
        if path_parts[0] == 'primary':
            path_parts = path_parts[1:]

        subject_id = path_parts[0]  # sub-f006
        sample_id = path_parts[1]  # sam-l
        segment_id = path_parts[2]  # sam-l-seg-t5
        filename = path_parts[3]  # B824_T5L_9um_2.jpx

        # Extract modality from filename (9um indicates microct)
        modality = 'microct' if '9um' in filename or '36um' in filename else 'unknown'

        return {
            'subject_id': subject_id,
            'sample_id': segment_id,
            'modality': modality,
            'filename': filename,
        }  # Use the full segment id as sample
    else:
        raise ValueError(f'Unexpected path structure: {path_parts}')


def create_csv_addresses(session):
    """Create addresses for CSV column headers from F006 fiber data."""
    # Actual CSV column headers from F006 fiber CSV files
    csv_headers = [
        'x',
        'y',
        'x_pix',
        'y_pix',
        'fiber_area',
        'myelin_area',
        'fiber_area_pix',
        'myelin_area_pix',
        'rho',
        'rho_pix',
        'phi',
        'hull_vertices',
        'perimeter',
        'hull_vertices_w_myel',
        'shortest_diameter',
        'longest_diameter',
        'shortest_diameter_w_myel',
        'longest_diameter_w_myel',
        'eff_fib_diam',
        'eff_fib_diam_w_myel',
        'median_myelin_thickness',
        'max_myelin_thickness',
        'myelinated',
        'chat',
        'unmyel_nf',
        'nav',
        'th_overlap_p',
        'c_estimate_nf_frac',
        'c_estimate_nf',
        'c_estimate_nav',
        'c_estimate_nav_frac',
    ]

    created_addresses = {}
    for header in csv_headers:
        addr = Addresses(addr_type='tabular-header', addr_field=header, value_type='single')
        created_addr = get_or_create(session, addr)
        created_addresses[header] = created_addr

    return created_addresses


def create_basic_descriptors(session):
    """Create basic descriptors needed for f006 dataset."""

    # === ROOT TABLES ===

    # Create Aspects (ROOT TABLE)
    aspects = [
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/volume', 'label': 'volume'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/length', 'label': 'length'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/diameter', 'label': 'diameter'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/area', 'label': 'area'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/thickness', 'label': 'thickness'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/position', 'label': 'position'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/pixel', 'label': 'pixel'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/pixel-area', 'label': 'pixel-area'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/perimeter', 'label': 'perimeter'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/vertex-x', 'label': 'vertex-x'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/vertex-y', 'label': 'vertex-y'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/polar-radius', 'label': 'polar-radius'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/polar-angle', 'label': 'polar-angle'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/percentage', 'label': 'percentage'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/channel-intensity', 'label': 'channel-intensity'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/aspect/fraction', 'label': 'fraction'},
    ]

    created_aspects = {}
    for aspect_data in aspects:
        aspect = Aspects(iri=aspect_data['iri'], label=aspect_data['label'])
        created_aspect = get_or_create(session, aspect)
        created_aspects[aspect_data['label']] = created_aspect

    # Create Units (ROOT TABLE)
    units = [
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/cubic-millimeter', 'label': 'mm3'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/millimeter', 'label': 'mm'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/micrometer', 'label': 'um'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/dimensionless', 'label': 'dimensionless'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/square-micrometer', 'label': 'um-squared'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/pixel-squared', 'label': 'pixel-squared'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/composite-key', 'label': 'composite-key'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/radian', 'label': 'radian'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/unit/percent', 'label': 'percent'},
    ]

    created_units = {}
    for unit_data in units:
        unit = Units(iri=unit_data['iri'], label=unit_data['label'])
        created_unit = get_or_create(session, unit)
        created_units[unit_data['label']] = created_unit

    # Create DescriptorsInst (ROOT TABLE)
    descriptors = [
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/human', 'label': 'human'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve-volume', 'label': 'nerve-volume'},
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve-cross-section',
            'label': 'nerve-cross-section',
        },
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve-fiber', 'label': 'nerve-fiber'},
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/myelin-sheath',
            'label': 'myelin-sheath',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-centroid',
            'label': 'fiber-centroid',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-cross-section',
            'label': 'fiber-cross-section',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-shortest-diameter',
            'label': 'fiber-shortest-diameter',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-longest-diameter',
            'label': 'fiber-longest-diameter',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-shortest-diameter-with-myelin',
            'label': 'fiber-shortest-diameter-with-myelin',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-longest-diameter-with-myelin',
            'label': 'fiber-longest-diameter-with-myelin',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-effective-diameter-with-myelin',
            'label': 'fiber-effective-diameter-with-myelin',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-perimeter',
            'label': 'fiber-perimeter',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-hull-vertex',
            'label': 'fiber-hull-vertex',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-hull-vertex-with-myelin',
            'label': 'fiber-hull-vertex-with-myelin',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/myelin-sheath-maximum',
            'label': 'myelin-sheath-maximum',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-myelination-status',
            'label': 'fiber-myelination-status',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-chat-status',
            'label': 'fiber-chat-status',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-unmyelinated-nf-status',
            'label': 'fiber-unmyelinated-nf-status',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-nav-status',
            'label': 'fiber-nav-status',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-polar-coordinates',
            'label': 'fiber-polar-coordinates',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-threshold-overlap',
            'label': 'fiber-threshold-overlap',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-nf-channel-estimate',
            'label': 'fiber-nf-channel-estimate',
        },
        {
            'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber-nav-channel-estimate',
            'label': 'fiber-nav-channel-estimate',
        },
    ]

    created_descriptors = {}
    for desc_data in descriptors:
        desc_inst = DescriptorsInst(iri=desc_data['iri'], label=desc_data['label'])
        created_desc = get_or_create(session, desc_inst)
        created_descriptors[desc_data['label']] = created_desc

    # Create ControlledTerms (ROOT TABLE)
    controlled_terms = [
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/microct', 'label': 'microct'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/true', 'label': 'true'},
        {'iri': 'https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/false', 'label': 'false'},
    ]

    created_terms = {}
    for term_data in controlled_terms:
        term = ControlledTerms(iri=term_data['iri'], label=term_data['label'])
        created_term = get_or_create(session, term)
        created_terms[term_data['label']] = created_term

    # Create Addresses (ROOT TABLE)
    const_addr = session.query(Addresses).filter_by(addr_type='constant', value_type='single').first()
    if not const_addr:
        const_addr = Addresses(addr_type='constant', addr_field=None, value_type='single')
        session.add(const_addr)
        session.commit()

    # Create tabular address for data fields
    tabular_addr = (
        session.query(Addresses).filter_by(addr_type='tabular-header', addr_field='volume', value_type='single').first()
    )
    if not tabular_addr:
        tabular_addr = Addresses(addr_type='tabular-header', addr_field='volume', value_type='single')
        session.add(tabular_addr)
        session.commit()

    # === INTERMEDIATE TABLES ===

    # Create DescriptorsCat (INTERMEDIATE TABLE - depends on DescriptorsInst)
    modality_desc = DescriptorsCat(
        domain=created_descriptors['nerve-volume'].id, range='controlled', label='hasDataAboutItModality'
    )
    modality_desc.descriptors_inst = created_descriptors['nerve-volume']
    created_modality_desc = get_or_create(session, modality_desc)

    # Create boolean categorical descriptors
    myelination_desc_cat = DescriptorsCat(
        domain=created_descriptors['fiber-myelination-status'].id, range='controlled', label='hasMyelinationStatus'
    )
    myelination_desc_cat.descriptors_inst = created_descriptors['fiber-myelination-status']
    created_myelination_desc_cat = get_or_create(session, myelination_desc_cat)

    chat_desc_cat = DescriptorsCat(
        domain=created_descriptors['fiber-chat-status'].id, range='controlled', label='hasChatStatus'
    )
    chat_desc_cat.descriptors_inst = created_descriptors['fiber-chat-status']
    created_chat_desc_cat = get_or_create(session, chat_desc_cat)

    unmyel_nf_desc_cat = DescriptorsCat(
        domain=created_descriptors['fiber-unmyelinated-nf-status'].id,
        range='controlled',
        label='hasUnmyelinatedNfStatus',
    )
    unmyel_nf_desc_cat.descriptors_inst = created_descriptors['fiber-unmyelinated-nf-status']
    created_unmyel_nf_desc_cat = get_or_create(session, unmyel_nf_desc_cat)

    nav_desc_cat = DescriptorsCat(
        domain=created_descriptors['fiber-nav-status'].id, range='controlled', label='hasNavStatus'
    )
    nav_desc_cat.descriptors_inst = created_descriptors['fiber-nav-status']
    created_nav_desc_cat = get_or_create(session, nav_desc_cat)

    # Create DescriptorsQuant (INTERMEDIATE TABLE - depends on Units, Aspects, DescriptorsInst)
    # Example 1: Nerve volume in mm3
    nerve_volume_desc = DescriptorsQuant(
        shape='scalar',
        label='nerve-volume-mm3',
        aggregation_type='instance',
        unit=created_units['mm3'].id,
        aspect=created_aspects['volume'].id,
        domain=created_descriptors['nerve-volume'].id,
        description='Volume of nerve segment in cubic millimeters',
    )
    nerve_volume_desc.units = created_units['mm3']
    nerve_volume_desc.aspects = created_aspects['volume']
    nerve_volume_desc.descriptors_inst = created_descriptors['nerve-volume']
    created_nerve_volume_desc = get_or_create(session, nerve_volume_desc)

    # Example 2: Nerve cross-section diameter in um
    nerve_diameter_desc = DescriptorsQuant(
        shape='scalar',
        label='nerve-cross-section-diameter-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['nerve-cross-section'].id,
        description='Diameter of nerve cross-section in micrometers',
    )
    nerve_diameter_desc.units = created_units['um']
    nerve_diameter_desc.aspects = created_aspects['diameter']
    nerve_diameter_desc.descriptors_inst = created_descriptors['nerve-cross-section']
    created_nerve_diameter_desc = get_or_create(session, nerve_diameter_desc)

    # Fiber area descriptor
    fiber_area_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-area-um2',
        aggregation_type='instance',
        unit=created_units['um-squared'].id,
        aspect=created_aspects['area'].id,
        domain=created_descriptors['fiber-cross-section'].id,
        description='Area of nerve fiber cross-section in square micrometers',
    )
    fiber_area_desc.units = created_units['um-squared']
    fiber_area_desc.aspects = created_aspects['area']
    fiber_area_desc.descriptors_inst = created_descriptors['fiber-cross-section']
    created_fiber_area_desc = get_or_create(session, fiber_area_desc)

    # Myelin thickness descriptor
    myelin_thickness_desc = DescriptorsQuant(
        shape='scalar',
        label='myelin-thickness-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['thickness'].id,
        domain=created_descriptors['myelin-sheath'].id,
        description='Thickness of myelin sheath in micrometers',
    )
    myelin_thickness_desc.units = created_units['um']
    myelin_thickness_desc.aspects = created_aspects['thickness']
    myelin_thickness_desc.descriptors_inst = created_descriptors['myelin-sheath']
    created_myelin_thickness_desc = get_or_create(session, myelin_thickness_desc)

    # Fiber diameter descriptor
    fiber_diameter_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-diameter-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['nerve-fiber'].id,
        description='Effective diameter of nerve fiber in micrometers',
    )
    fiber_diameter_desc.units = created_units['um']
    fiber_diameter_desc.aspects = created_aspects['diameter']
    fiber_diameter_desc.descriptors_inst = created_descriptors['nerve-fiber']
    created_fiber_diameter_desc = get_or_create(session, fiber_diameter_desc)

    # X coordinate descriptor (micrometers)
    x_coord_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-x-coordinate-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['position'].id,
        domain=created_descriptors['fiber-centroid'].id,
        description='X coordinate of fiber centroid in micrometers',
    )
    x_coord_desc.units = created_units['um']
    x_coord_desc.aspects = created_aspects['position']
    x_coord_desc.descriptors_inst = created_descriptors['fiber-centroid']
    created_x_coord_desc = get_or_create(session, x_coord_desc)

    # Y coordinate descriptor (micrometers)
    y_coord_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-y-coordinate-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['position'].id,
        domain=created_descriptors['fiber-centroid'].id,
        description='Y coordinate of fiber centroid in micrometers',
    )
    y_coord_desc.units = created_units['um']
    y_coord_desc.aspects = created_aspects['position']
    y_coord_desc.descriptors_inst = created_descriptors['fiber-centroid']
    created_y_coord_desc = get_or_create(session, y_coord_desc)

    # X coordinate descriptor (pixels)
    x_pix_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-x-coordinate-pix',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,  # pixels are dimensionless
        aspect=created_aspects['pixel'].id,
        domain=created_descriptors['fiber-centroid'].id,
        description='X coordinate of fiber centroid in pixels',
    )
    x_pix_desc.units = created_units['dimensionless']
    x_pix_desc.aspects = created_aspects['pixel']
    x_pix_desc.descriptors_inst = created_descriptors['fiber-centroid']
    created_x_pix_desc = get_or_create(session, x_pix_desc)

    # Y coordinate descriptor (pixels)
    y_pix_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-y-coordinate-pix',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,  # pixels are dimensionless
        aspect=created_aspects['pixel'].id,
        domain=created_descriptors['fiber-centroid'].id,
        description='Y coordinate of fiber centroid in pixels',
    )
    y_pix_desc.units = created_units['dimensionless']
    y_pix_desc.aspects = created_aspects['pixel']
    y_pix_desc.descriptors_inst = created_descriptors['fiber-centroid']
    created_y_pix_desc = get_or_create(session, y_pix_desc)

    # Myelin area descriptor (square micrometers)
    myelin_area_desc = DescriptorsQuant(
        shape='scalar',
        label='myelin-area-um2',
        aggregation_type='instance',
        unit=created_units['um-squared'].id,
        aspect=created_aspects['area'].id,
        domain=created_descriptors['fiber-cross-section'].id,
        description='Area of myelin sheath in square micrometers',
    )
    myelin_area_desc.units = created_units['um-squared']
    myelin_area_desc.aspects = created_aspects['area']
    myelin_area_desc.descriptors_inst = created_descriptors['fiber-cross-section']
    created_myelin_area_desc = get_or_create(session, myelin_area_desc)

    # Fiber area descriptor (pixels)
    fiber_area_pix_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-area-pix',
        aggregation_type='instance',
        unit=created_units['pixel-squared'].id,
        aspect=created_aspects['pixel-area'].id,
        domain=created_descriptors['fiber-cross-section'].id,
        description='Area of fiber cross-section in pixels',
    )
    fiber_area_pix_desc.units = created_units['pixel-squared']
    fiber_area_pix_desc.aspects = created_aspects['pixel-area']
    fiber_area_pix_desc.descriptors_inst = created_descriptors['fiber-cross-section']
    created_fiber_area_pix_desc = get_or_create(session, fiber_area_pix_desc)

    # Myelin area descriptor (pixels)
    myelin_area_pix_desc = DescriptorsQuant(
        shape='scalar',
        label='myelin-area-pix',
        aggregation_type='instance',
        unit=created_units['pixel-squared'].id,
        aspect=created_aspects['pixel-area'].id,
        domain=created_descriptors['fiber-cross-section'].id,
        description='Area of myelin sheath in pixels',
    )
    myelin_area_pix_desc.units = created_units['pixel-squared']
    myelin_area_pix_desc.aspects = created_aspects['pixel-area']
    myelin_area_pix_desc.descriptors_inst = created_descriptors['fiber-cross-section']
    created_myelin_area_pix_desc = get_or_create(session, myelin_area_pix_desc)

    # Shortest diameter descriptor (without myelin)
    shortest_diameter_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-shortest-diameter-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['fiber-shortest-diameter'].id,
        description='Shortest diameter of fiber cross-section in micrometers',
    )
    shortest_diameter_desc.units = created_units['um']
    shortest_diameter_desc.aspects = created_aspects['diameter']
    shortest_diameter_desc.descriptors_inst = created_descriptors['fiber-shortest-diameter']
    created_shortest_diameter_desc = get_or_create(session, shortest_diameter_desc)

    # Longest diameter descriptor (without myelin)
    longest_diameter_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-longest-diameter-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['fiber-longest-diameter'].id,
        description='Longest diameter of fiber cross-section in micrometers',
    )
    longest_diameter_desc.units = created_units['um']
    longest_diameter_desc.aspects = created_aspects['diameter']
    longest_diameter_desc.descriptors_inst = created_descriptors['fiber-longest-diameter']
    created_longest_diameter_desc = get_or_create(session, longest_diameter_desc)

    # Shortest diameter with myelin descriptor
    shortest_diameter_myel_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-shortest-diameter-with-myelin-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['fiber-shortest-diameter-with-myelin'].id,
        description='Shortest diameter of fiber including myelin sheath in micrometers',
    )
    shortest_diameter_myel_desc.units = created_units['um']
    shortest_diameter_myel_desc.aspects = created_aspects['diameter']
    shortest_diameter_myel_desc.descriptors_inst = created_descriptors['fiber-shortest-diameter-with-myelin']
    created_shortest_diameter_myel_desc = get_or_create(session, shortest_diameter_myel_desc)

    # Longest diameter with myelin descriptor
    longest_diameter_myel_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-longest-diameter-with-myelin-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['fiber-longest-diameter-with-myelin'].id,
        description='Longest diameter of fiber including myelin sheath in micrometers',
    )
    longest_diameter_myel_desc.units = created_units['um']
    longest_diameter_myel_desc.aspects = created_aspects['diameter']
    longest_diameter_myel_desc.descriptors_inst = created_descriptors['fiber-longest-diameter-with-myelin']
    created_longest_diameter_myel_desc = get_or_create(session, longest_diameter_myel_desc)

    # Effective diameter with myelin descriptor
    eff_diameter_myel_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-effective-diameter-with-myelin-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['diameter'].id,
        domain=created_descriptors['fiber-effective-diameter-with-myelin'].id,
        description='Effective diameter of fiber including myelin sheath in micrometers',
    )
    eff_diameter_myel_desc.units = created_units['um']
    eff_diameter_myel_desc.aspects = created_aspects['diameter']
    eff_diameter_myel_desc.descriptors_inst = created_descriptors['fiber-effective-diameter-with-myelin']
    created_eff_diameter_myel_desc = get_or_create(session, eff_diameter_myel_desc)

    # Perimeter descriptor
    perimeter_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-perimeter-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['perimeter'].id,
        domain=created_descriptors['fiber-perimeter'].id,
        description='Perimeter of fiber cross-section in micrometers',
    )
    perimeter_desc.units = created_units['um']
    perimeter_desc.aspects = created_aspects['perimeter']
    perimeter_desc.descriptors_inst = created_descriptors['fiber-perimeter']
    created_perimeter_desc = get_or_create(session, perimeter_desc)

    # Hull vertex X descriptor (without myelin)
    hull_vertex_x_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-hull-vertex-x-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['vertex-x'].id,
        domain=created_descriptors['fiber-hull-vertex'].id,
        description='X coordinate of fiber hull vertex in micrometers',
    )
    hull_vertex_x_desc.units = created_units['um']
    hull_vertex_x_desc.aspects = created_aspects['vertex-x']
    hull_vertex_x_desc.descriptors_inst = created_descriptors['fiber-hull-vertex']
    created_hull_vertex_x_desc = get_or_create(session, hull_vertex_x_desc)

    # Hull vertex Y descriptor (without myelin)
    hull_vertex_y_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-hull-vertex-y-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['vertex-y'].id,
        domain=created_descriptors['fiber-hull-vertex'].id,
        description='Y coordinate of fiber hull vertex in micrometers',
    )
    hull_vertex_y_desc.units = created_units['um']
    hull_vertex_y_desc.aspects = created_aspects['vertex-y']
    hull_vertex_y_desc.descriptors_inst = created_descriptors['fiber-hull-vertex']
    created_hull_vertex_y_desc = get_or_create(session, hull_vertex_y_desc)

    # Hull vertex X descriptor (with myelin)
    hull_vertex_x_myel_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-hull-vertex-x-with-myelin-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['vertex-x'].id,
        domain=created_descriptors['fiber-hull-vertex-with-myelin'].id,
        description='X coordinate of fiber hull vertex including myelin in micrometers',
    )
    hull_vertex_x_myel_desc.units = created_units['um']
    hull_vertex_x_myel_desc.aspects = created_aspects['vertex-x']
    hull_vertex_x_myel_desc.descriptors_inst = created_descriptors['fiber-hull-vertex-with-myelin']
    created_hull_vertex_x_myel_desc = get_or_create(session, hull_vertex_x_myel_desc)

    # Hull vertex Y descriptor (with myelin)
    hull_vertex_y_myel_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-hull-vertex-y-with-myelin-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['vertex-y'].id,
        domain=created_descriptors['fiber-hull-vertex-with-myelin'].id,
        description='Y coordinate of fiber hull vertex including myelin in micrometers',
    )
    hull_vertex_y_myel_desc.units = created_units['um']
    hull_vertex_y_myel_desc.aspects = created_aspects['vertex-y']
    hull_vertex_y_myel_desc.descriptors_inst = created_descriptors['fiber-hull-vertex-with-myelin']
    created_hull_vertex_y_myel_desc = get_or_create(session, hull_vertex_y_myel_desc)

    # Maximum myelin thickness descriptor
    max_myelin_thickness_desc = DescriptorsQuant(
        shape='scalar',
        label='myelin-maximum-thickness-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['thickness'].id,
        domain=created_descriptors['myelin-sheath-maximum'].id,
        description='Maximum thickness of myelin sheath in micrometers',
    )
    max_myelin_thickness_desc.units = created_units['um']
    max_myelin_thickness_desc.aspects = created_aspects['thickness']
    max_myelin_thickness_desc.descriptors_inst = created_descriptors['myelin-sheath-maximum']
    created_max_myelin_thickness_desc = get_or_create(session, max_myelin_thickness_desc)

    # Rho (polar radius) descriptor in micrometers
    rho_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-polar-radius-um',
        aggregation_type='instance',
        unit=created_units['um'].id,
        aspect=created_aspects['polar-radius'].id,
        domain=created_descriptors['fiber-polar-coordinates'].id,
        description='Polar coordinate radius of fiber centroid in micrometers',
    )
    rho_desc.units = created_units['um']
    rho_desc.aspects = created_aspects['polar-radius']
    rho_desc.descriptors_inst = created_descriptors['fiber-polar-coordinates']
    created_rho_desc = get_or_create(session, rho_desc)

    # Rho (polar radius) descriptor in pixels
    rho_pix_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-polar-radius-pix',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,
        aspect=created_aspects['polar-radius'].id,
        domain=created_descriptors['fiber-polar-coordinates'].id,
        description='Polar coordinate radius of fiber centroid in pixels',
    )
    rho_pix_desc.units = created_units['dimensionless']
    rho_pix_desc.aspects = created_aspects['polar-radius']
    rho_pix_desc.descriptors_inst = created_descriptors['fiber-polar-coordinates']
    created_rho_pix_desc = get_or_create(session, rho_pix_desc)

    # Phi (polar angle) descriptor
    phi_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-polar-angle-rad',
        aggregation_type='instance',
        unit=created_units['radian'].id,
        aspect=created_aspects['polar-angle'].id,
        domain=created_descriptors['fiber-polar-coordinates'].id,
        description='Polar coordinate angle of fiber centroid in radians',
    )
    phi_desc.units = created_units['radian']
    phi_desc.aspects = created_aspects['polar-angle']
    phi_desc.descriptors_inst = created_descriptors['fiber-polar-coordinates']
    created_phi_desc = get_or_create(session, phi_desc)

    # Threshold overlap percentage descriptor
    th_overlap_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-threshold-overlap-percent',
        aggregation_type='instance',
        unit=created_units['percent'].id,
        aspect=created_aspects['percentage'].id,
        domain=created_descriptors['fiber-threshold-overlap'].id,
        description='Percentage of fiber area overlapping with threshold region',
    )
    th_overlap_desc.units = created_units['percent']
    th_overlap_desc.aspects = created_aspects['percentage']
    th_overlap_desc.descriptors_inst = created_descriptors['fiber-threshold-overlap']
    created_th_overlap_desc = get_or_create(session, th_overlap_desc)

    # NF channel estimate descriptor
    c_estimate_nf_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-nf-channel-estimate',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,
        aspect=created_aspects['channel-intensity'].id,
        domain=created_descriptors['fiber-nf-channel-estimate'].id,
        description='Estimated intensity value for NF (neurofilament) channel',
    )
    c_estimate_nf_desc.units = created_units['dimensionless']
    c_estimate_nf_desc.aspects = created_aspects['channel-intensity']
    c_estimate_nf_desc.descriptors_inst = created_descriptors['fiber-nf-channel-estimate']
    created_c_estimate_nf_desc = get_or_create(session, c_estimate_nf_desc)

    # NF channel estimate fraction descriptor
    c_estimate_nf_frac_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-nf-channel-estimate-fraction',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,
        aspect=created_aspects['fraction'].id,
        domain=created_descriptors['fiber-nf-channel-estimate'].id,
        description='Fraction of fiber area with NF channel signal',
    )
    c_estimate_nf_frac_desc.units = created_units['dimensionless']
    c_estimate_nf_frac_desc.aspects = created_aspects['fraction']
    c_estimate_nf_frac_desc.descriptors_inst = created_descriptors['fiber-nf-channel-estimate']
    created_c_estimate_nf_frac_desc = get_or_create(session, c_estimate_nf_frac_desc)

    # Nav channel estimate descriptor
    c_estimate_nav_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-nav-channel-estimate',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,
        aspect=created_aspects['channel-intensity'].id,
        domain=created_descriptors['fiber-nav-channel-estimate'].id,
        description='Estimated intensity value for Nav (sodium channel) channel',
    )
    c_estimate_nav_desc.units = created_units['dimensionless']
    c_estimate_nav_desc.aspects = created_aspects['channel-intensity']
    c_estimate_nav_desc.descriptors_inst = created_descriptors['fiber-nav-channel-estimate']
    created_c_estimate_nav_desc = get_or_create(session, c_estimate_nav_desc)

    # Nav channel estimate fraction descriptor
    c_estimate_nav_frac_desc = DescriptorsQuant(
        shape='scalar',
        label='fiber-nav-channel-estimate-fraction',
        aggregation_type='instance',
        unit=created_units['dimensionless'].id,
        aspect=created_aspects['fraction'].id,
        domain=created_descriptors['fiber-nav-channel-estimate'].id,
        description='Fraction of fiber area with Nav channel signal',
    )
    c_estimate_nav_frac_desc.units = created_units['dimensionless']
    c_estimate_nav_frac_desc.aspects = created_aspects['fraction']
    c_estimate_nav_frac_desc.descriptors_inst = created_descriptors['fiber-nav-channel-estimate']
    created_c_estimate_nav_frac_desc = get_or_create(session, c_estimate_nav_frac_desc)

    return {
        'aspects': created_aspects,
        'units': created_units,
        'descriptors': created_descriptors,
        'terms': created_terms,
        'modality_desc': created_modality_desc,
        'myelination_desc_cat': created_myelination_desc_cat,
        'chat_desc_cat': created_chat_desc_cat,
        'unmyel_nf_desc_cat': created_unmyel_nf_desc_cat,
        'nav_desc_cat': created_nav_desc_cat,
        'nerve_volume_desc': created_nerve_volume_desc,
        'nerve_diameter_desc': created_nerve_diameter_desc,
        'fiber_area_desc': created_fiber_area_desc,
        'myelin_thickness_desc': created_myelin_thickness_desc,
        'fiber_diameter_desc': created_fiber_diameter_desc,
        'x_coord_desc': created_x_coord_desc,
        'y_coord_desc': created_y_coord_desc,
        'x_pix_desc': created_x_pix_desc,
        'y_pix_desc': created_y_pix_desc,
        'myelin_area_desc': created_myelin_area_desc,
        'fiber_area_pix_desc': created_fiber_area_pix_desc,
        'myelin_area_pix_desc': created_myelin_area_pix_desc,
        'shortest_diameter_desc': created_shortest_diameter_desc,
        'longest_diameter_desc': created_longest_diameter_desc,
        'shortest_diameter_myel_desc': created_shortest_diameter_myel_desc,
        'longest_diameter_myel_desc': created_longest_diameter_myel_desc,
        'eff_diameter_myel_desc': created_eff_diameter_myel_desc,
        'perimeter_desc': created_perimeter_desc,
        'hull_vertex_x_desc': created_hull_vertex_x_desc,
        'hull_vertex_y_desc': created_hull_vertex_y_desc,
        'hull_vertex_x_myel_desc': created_hull_vertex_x_myel_desc,
        'hull_vertex_y_myel_desc': created_hull_vertex_y_myel_desc,
        'max_myelin_thickness_desc': created_max_myelin_thickness_desc,
        'rho_desc': created_rho_desc,
        'rho_pix_desc': created_rho_pix_desc,
        'phi_desc': created_phi_desc,
        'th_overlap_desc': created_th_overlap_desc,
        'c_estimate_nf_desc': created_c_estimate_nf_desc,
        'c_estimate_nf_frac_desc': created_c_estimate_nf_frac_desc,
        'c_estimate_nav_desc': created_c_estimate_nav_desc,
        'c_estimate_nav_frac_desc': created_c_estimate_nav_frac_desc,
        'const_addr': const_addr,
        'tabular_addr': tabular_addr,
    }


def ingest_objects_table(session, metadata, components):
    """Ingest objects into the objects table using ORM."""

    print('=== Ingesting Objects Table ===')

    # Create dataset object
    dataset_obj = Objects(id=DATASET_UUID, id_type='dataset', id_file=None, id_internal=None)
    dataset_result = get_or_create(session, dataset_obj)
    print(f'Created/found dataset object: {str(dataset_result.id)}')

    # Create package objects for each jpx file only
    created_objects = []
    for item in metadata['data']:
        # Skip non-jpx files
        if item.get('mimetype') != 'image/jpx':
            continue

        # Skip if no dataset_relative_path or if it's empty/root
        if not item.get('dataset_relative_path') or item['dataset_relative_path'] == '':
            continue

        package_id = uuid.uuid4()  # Generate UUID for package

        package_obj = Objects(id=package_id, id_type='package', id_file=item.get('remote_inode_id'), id_internal=None)
        # Set relationship to dataset
        package_obj.objects_ = dataset_result

        package_result = get_or_create(session, package_obj)
        created_objects.append(package_result)
        print(f'Created package object: {str(package_result.id)} for file_id: {package_result.id_file}')

    return dataset_result, created_objects


def ingest_instances_table(session, metadata, components, dataset_obj):
    """Ingest instances into the values_inst table using ORM."""

    print('=== Ingesting Values Instance Table ===')

    created_instances = {}
    processed_subjects = set()
    processed_samples = set()

    for item in metadata['data']:
        # Skip non-jpx files
        if item.get('mimetype') != 'image/jpx':
            continue

        # Skip if no dataset_relative_path or if it's empty/root
        if not item.get('dataset_relative_path') or item['dataset_relative_path'] == '':
            continue

        path_parts = pathlib.Path(item['dataset_relative_path']).parts
        parsed_path = parse_path_structure(path_parts)

        # Create subject instance (if not already created)
        subject_id = parsed_path['subject_id']
        if subject_id not in processed_subjects:
            subject_inst = ValuesInst(
                type='subject',
                desc_inst=components['descriptors']['human'].id,
                dataset=dataset_obj.id,
                id_formal=subject_id,
                id_sub=subject_id,
                id_sam=None,
            )
            # Set relationships
            subject_inst.objects = dataset_obj
            subject_inst.descriptors_inst = components['descriptors']['human']

            subject_result = get_or_create(session, subject_inst)
            created_instances[subject_id] = subject_result
            processed_subjects.add(subject_id)
            print(f'Created subject instance: {subject_result.id_formal}')

        # Create sample instance (if not already created)
        sample_id = parsed_path['sample_id']
        sample_key = f'{subject_id}_{sample_id}'
        if sample_key not in processed_samples:
            sample_inst = ValuesInst(
                type='sample',
                desc_inst=components['descriptors']['nerve-volume'].id,
                dataset=dataset_obj.id,
                id_formal=sample_id,
                id_sub=subject_id,
                id_sam=sample_id,
            )
            # Set relationships
            sample_inst.objects = dataset_obj
            sample_inst.descriptors_inst = components['descriptors']['nerve-volume']

            sample_result = get_or_create(session, sample_inst)
            created_instances[sample_key] = sample_result
            processed_samples.add(sample_key)
            print(f'Created sample instance: {sample_result.id_formal}')

    return created_instances


def create_obj_desc_mappings(session, components, package_objects):
    """Create ObjDesc* mappings that tell the system where to find data in packages."""

    print('=== Creating ObjDesc Mappings ===')

    created_mappings = {'obj_desc_inst': [], 'obj_desc_cat': [], 'obj_desc_quant': []}

    # For each package, create mappings
    for package in package_objects:
        # ObjDescInst - Maps package to instance descriptors
        # This tells the system that this package contains data about nerve-volume instances
        obj_desc_inst = ObjDescInst(
            object=package.id,
            desc_inst=components['descriptors']['nerve-volume'].id,
            addr_field=components['const_addr'].id,
        )
        obj_desc_inst.objects = package
        obj_desc_inst.descriptors_inst = components['descriptors']['nerve-volume']
        obj_desc_inst.addresses_field = components['const_addr']

        result = get_or_create(session, obj_desc_inst)
        created_mappings['obj_desc_inst'].append(result)

        # ObjDescCat - Maps package to categorical descriptors
        # This tells the system that this package contains modality data
        obj_desc_cat = ObjDescCat(
            object=package.id, desc_cat=components['modality_desc'].id, addr_field=components['const_addr'].id
        )
        obj_desc_cat.objects = package
        obj_desc_cat.descriptors_cat = components['modality_desc']
        obj_desc_cat.addresses_ = components['const_addr']

        result = get_or_create(session, obj_desc_cat)
        created_mappings['obj_desc_cat'].append(result)

        # ObjDescQuant - Maps package to quantitative descriptors
        # This tells the system that this package contains volume measurements
        obj_desc_quant = ObjDescQuant(
            object=package.id, desc_quant=components['nerve_volume_desc'].id, addr_field=components['tabular_addr'].id
        )
        obj_desc_quant.objects = package
        obj_desc_quant.descriptors_quant = components['nerve_volume_desc']
        obj_desc_quant.addresses_field = components['tabular_addr']

        result = get_or_create(session, obj_desc_quant)
        created_mappings['obj_desc_quant'].append(result)

        print(f'Created mappings for package: {str(package.id)}')

    return created_mappings


def create_leaf_values(session, metadata, components, dataset_obj, package_objects, instances, mappings):
    """Create leaf table values using actual CSV data from Pennsieve."""

    print('=== Creating Leaf Table Values with CSV Data ===')

    created_values = {'values_cat': [], 'values_quant': []}

    # Initialize Pennsieve client
    try:
        client = PennsieveClient()
    except Exception as e:
        print(f'Warning: Could not initialize Pennsieve client: {e}')
        print('Falling back to placeholder data')
        client = None

    # Process each file to create values
    package_idx = 0
    csv_file_count = 0

    for item in metadata['data']:
        # Process JPX files for modality info
        if item.get('mimetype') == 'image/jpx':
            # Skip if no dataset_relative_path or if it's empty/root
            if not item.get('dataset_relative_path') or item['dataset_relative_path'] == '':
                continue

            package = package_objects[package_idx]
            package_idx += 1

            path_parts = pathlib.Path(item['dataset_relative_path']).parts
            parsed_path = parse_path_structure(path_parts)

            # Get the sample instance for this file
            sample_key = f"{parsed_path['subject_id']}_{parsed_path['sample_id']}"
            sample_instance = instances[sample_key]

            # Create categorical value for modality
            values_cat = ValuesCat(
                value_controlled=components['terms']['microct'].id,
                object=package.id,
                desc_inst=components['descriptors']['nerve-volume'].id,
                desc_cat=components['modality_desc'].id,
                instance=sample_instance.id,
            )

            # Set all relationships
            values_cat.controlled_terms = components['terms']['microct']
            values_cat.descriptors_cat = components['modality_desc']
            values_cat.descriptors_inst = components['descriptors']['nerve-volume']
            values_cat.values_inst = sample_instance
            values_cat.objects = package

            session.add(values_cat)
            session.commit()
            created_values['values_cat'].append(values_cat)
            print(f"Created categorical value for {parsed_path['sample_id']}: modality={parsed_path['modality']}")

        # Process CSV files for quantitative data
        # NOTE: CSV processing is disabled in base f006.py - use f006_csv.py for CSV support
        elif False and item.get('mimetype') == 'text/csv':
            # Parse CSV path
            if not item.get('dataset_relative_path'):
                continue

            path_parts = pathlib.Path(item['dataset_relative_path']).parts
            parsed_csv = parse_csv_path_structure(path_parts)

            # Check if it's a fiber CSV file by looking at the path
            csv_name = item.get('name', '')
            csv_path_str = item.get('dataset_relative_path', '')
            if not parsed_csv or ('_fibers.csv' not in csv_name and '_fibers.csv' not in csv_path_str):
                continue

            csv_file_count += 1
            csv_filename = item.get('name', pathlib.Path(csv_path_str).name)
            print(f'\nProcessing CSV file: {csv_filename}')

            # Initialize client if not already done
            if not client:
                try:
                    client = PennsieveClient()
                    print('Initialized Pennsieve client for CSV download')
                except Exception as e:
                    print(f'Failed to initialize Pennsieve client: {e}')
                    continue

            # Download and read CSV
            csv_path = download_csv_from_pennsieve(client, item)

            if not csv_path:
                print(f'Failed to download CSV: {csv_filename}')
                continue

            csv_data = read_csv_data(csv_path)
            if not csv_data:
                print(f'No data in CSV: {csv_filename}')
                continue

            # Get the sample instance for this CSV
            sample_key = f"{parsed_csv['subject_id']}_{parsed_csv['sample_id']}"
            if sample_key not in instances:
                print(f'No instance found for {sample_key}, skipping')
                continue

            sample_instance = instances[sample_key]

            # Process CSV data to extract measurements
            # Process actual F006 fiber measurements
            for row_idx, row in enumerate(csv_data):
                # Create a package object for this fiber (row)
                csv_package_id = uuid.uuid4()
                # Use the file_id from the item, which should be an integer
                file_id = item.get('file_id') or item.get('remote_inode_id')
                csv_package = Objects(
                    id=csv_package_id,
                    id_type='package',
                    id_file=file_id,  # This should be just the integer file ID
                    id_internal=None,
                )
                csv_package.objects_ = dataset_obj
                csv_package_result = get_or_create(session, csv_package)

                # Extract fiber area
                if 'fiber_area' in row and row['fiber_area']:
                    try:
                        fiber_area_value = float(row['fiber_area'])

                        values_quant = ValuesQuant(
                            value=fiber_area_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-cross-section'].id,
                            desc_quant=components['fiber_area_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': fiber_area_value, 'unit': 'um^2', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-cross-section']
                        values_quant.descriptors_quant = components['fiber_area_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract effective fiber diameter
                if 'eff_fib_diam' in row and row['eff_fib_diam']:
                    try:
                        fiber_diam_value = float(row['eff_fib_diam'])

                        values_quant = ValuesQuant(
                            value=fiber_diam_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['nerve-fiber'].id,
                            desc_quant=components['fiber_diameter_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': fiber_diam_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['nerve-fiber']
                        values_quant.descriptors_quant = components['fiber_diameter_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract median myelin thickness
                if 'median_myelin_thickness' in row and row['median_myelin_thickness']:
                    try:
                        myelin_thickness_value = float(row['median_myelin_thickness'])

                        values_quant = ValuesQuant(
                            value=myelin_thickness_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['myelin-sheath'].id,
                            desc_quant=components['myelin_thickness_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': myelin_thickness_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['myelin-sheath']
                        values_quant.descriptors_quant = components['myelin_thickness_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract maximum myelin thickness
                if 'max_myelin_thickness' in row and row['max_myelin_thickness']:
                    try:
                        max_myelin_thickness_value = float(row['max_myelin_thickness'])

                        values_quant = ValuesQuant(
                            value=max_myelin_thickness_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['myelin-sheath-maximum'].id,
                            desc_quant=components['max_myelin_thickness_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': max_myelin_thickness_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['myelin-sheath-maximum']
                        values_quant.descriptors_quant = components['max_myelin_thickness_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract X coordinate (micrometers)
                if 'x' in row and row['x']:
                    try:
                        x_value = float(row['x'])

                        values_quant = ValuesQuant(
                            value=x_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-centroid'].id,
                            desc_quant=components['x_coord_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': x_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-centroid']
                        values_quant.descriptors_quant = components['x_coord_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract Y coordinate (micrometers)
                if 'y' in row and row['y']:
                    try:
                        y_value = float(row['y'])

                        values_quant = ValuesQuant(
                            value=y_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-centroid'].id,
                            desc_quant=components['y_coord_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': y_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-centroid']
                        values_quant.descriptors_quant = components['y_coord_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract X coordinate (pixels)
                if 'x_pix' in row and row['x_pix']:
                    try:
                        x_pix_value = float(row['x_pix'])

                        values_quant = ValuesQuant(
                            value=x_pix_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-centroid'].id,
                            desc_quant=components['x_pix_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': x_pix_value, 'unit': 'pixels', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-centroid']
                        values_quant.descriptors_quant = components['x_pix_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract Y coordinate (pixels)
                if 'y_pix' in row and row['y_pix']:
                    try:
                        y_pix_value = float(row['y_pix'])

                        values_quant = ValuesQuant(
                            value=y_pix_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-centroid'].id,
                            desc_quant=components['y_pix_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': y_pix_value, 'unit': 'pixels', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-centroid']
                        values_quant.descriptors_quant = components['y_pix_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract myelin area (micrometers)
                if 'myelin_area' in row and row['myelin_area']:
                    try:
                        myelin_area_value = float(row['myelin_area'])

                        values_quant = ValuesQuant(
                            value=myelin_area_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-cross-section'].id,
                            desc_quant=components['myelin_area_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': myelin_area_value, 'unit': 'um^2', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-cross-section']
                        values_quant.descriptors_quant = components['myelin_area_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract fiber area (pixels)
                if 'fiber_area_pix' in row and row['fiber_area_pix']:
                    try:
                        fiber_area_pix_value = float(row['fiber_area_pix'])

                        values_quant = ValuesQuant(
                            value=fiber_area_pix_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-cross-section'].id,
                            desc_quant=components['fiber_area_pix_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': fiber_area_pix_value, 'unit': 'pixels^2', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-cross-section']
                        values_quant.descriptors_quant = components['fiber_area_pix_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract myelin area (pixels)
                if 'myelin_area_pix' in row and row['myelin_area_pix']:
                    try:
                        myelin_area_pix_value = float(row['myelin_area_pix'])

                        values_quant = ValuesQuant(
                            value=myelin_area_pix_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-cross-section'].id,
                            desc_quant=components['myelin_area_pix_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': myelin_area_pix_value, 'unit': 'pixels^2', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-cross-section']
                        values_quant.descriptors_quant = components['myelin_area_pix_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract shortest diameter
                if 'shortest_diameter' in row and row['shortest_diameter']:
                    try:
                        shortest_diam_value = float(row['shortest_diameter'])

                        values_quant = ValuesQuant(
                            value=shortest_diam_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-shortest-diameter'].id,
                            desc_quant=components['shortest_diameter_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': shortest_diam_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-shortest-diameter']
                        values_quant.descriptors_quant = components['shortest_diameter_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract longest diameter
                if 'longest_diameter' in row and row['longest_diameter']:
                    try:
                        longest_diam_value = float(row['longest_diameter'])

                        values_quant = ValuesQuant(
                            value=longest_diam_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-longest-diameter'].id,
                            desc_quant=components['longest_diameter_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': longest_diam_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-longest-diameter']
                        values_quant.descriptors_quant = components['longest_diameter_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract shortest diameter with myelin
                if 'shortest_diameter_w_myel' in row and row['shortest_diameter_w_myel']:
                    try:
                        shortest_diam_myel_value = float(row['shortest_diameter_w_myel'])

                        values_quant = ValuesQuant(
                            value=shortest_diam_myel_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-shortest-diameter-with-myelin'].id,
                            desc_quant=components['shortest_diameter_myel_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': shortest_diam_myel_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-shortest-diameter-with-myelin']
                        values_quant.descriptors_quant = components['shortest_diameter_myel_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract longest diameter with myelin
                if 'longest_diameter_w_myel' in row and row['longest_diameter_w_myel']:
                    try:
                        longest_diam_myel_value = float(row['longest_diameter_w_myel'])

                        values_quant = ValuesQuant(
                            value=longest_diam_myel_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-longest-diameter-with-myelin'].id,
                            desc_quant=components['longest_diameter_myel_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': longest_diam_myel_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-longest-diameter-with-myelin']
                        values_quant.descriptors_quant = components['longest_diameter_myel_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract effective fiber diameter with myelin
                if 'eff_fib_diam_w_myel' in row and row['eff_fib_diam_w_myel']:
                    try:
                        eff_diam_myel_value = float(row['eff_fib_diam_w_myel'])

                        values_quant = ValuesQuant(
                            value=eff_diam_myel_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-effective-diameter-with-myelin'].id,
                            desc_quant=components['eff_diameter_myel_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': eff_diam_myel_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors'][
                            'fiber-effective-diameter-with-myelin'
                        ]
                        values_quant.descriptors_quant = components['eff_diameter_myel_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract perimeter
                if 'perimeter' in row and row['perimeter']:
                    try:
                        perimeter_value = float(row['perimeter'])

                        values_quant = ValuesQuant(
                            value=perimeter_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-perimeter'].id,
                            desc_quant=components['perimeter_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': perimeter_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-perimeter']
                        values_quant.descriptors_quant = components['perimeter_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract hull vertices (without myelin)
                if 'hull_vertices' in row and row['hull_vertices']:
                    try:
                        # Parse the string representation of list of lists
                        hull_vertices = ast.literal_eval(row['hull_vertices'])

                        # Store each vertex atomically with composite key
                        for vertex_idx, vertex in enumerate(hull_vertices):
                            if len(vertex) >= 2:
                                # Store X coordinate
                                x_value = float(vertex[0])
                                values_quant_x = ValuesQuant(
                                    value=x_value,
                                    object=csv_package_result.id,
                                    desc_inst=components['descriptors']['fiber-hull-vertex'].id,
                                    desc_quant=components['hull_vertex_x_desc'].id,
                                    instance=sample_instance.id,
                                    value_blob={
                                        'value': x_value,
                                        'unit': 'um',
                                        'source': 'csv',
                                        'vertex_index': vertex_idx,
                                        'composite_key': f'hull_vertex_{row_idx}_{vertex_idx}_x',
                                    },
                                )
                                values_quant_x.descriptors_inst = components['descriptors']['fiber-hull-vertex']
                                values_quant_x.descriptors_quant = components['hull_vertex_x_desc']
                                values_quant_x.values_inst = sample_instance
                                values_quant_x.objects = csv_package_result
                                session.add(values_quant_x)
                                created_values['values_quant'].append(values_quant_x)

                                # Store Y coordinate
                                y_value = float(vertex[1])
                                values_quant_y = ValuesQuant(
                                    value=y_value,
                                    object=csv_package_result.id,
                                    desc_inst=components['descriptors']['fiber-hull-vertex'].id,
                                    desc_quant=components['hull_vertex_y_desc'].id,
                                    instance=sample_instance.id,
                                    value_blob={
                                        'value': y_value,
                                        'unit': 'um',
                                        'source': 'csv',
                                        'vertex_index': vertex_idx,
                                        'composite_key': f'hull_vertex_{row_idx}_{vertex_idx}_y',
                                    },
                                )
                                values_quant_y.descriptors_inst = components['descriptors']['fiber-hull-vertex']
                                values_quant_y.descriptors_quant = components['hull_vertex_y_desc']
                                values_quant_y.values_inst = sample_instance
                                values_quant_y.objects = csv_package_result
                                session.add(values_quant_y)
                                created_values['values_quant'].append(values_quant_y)

                    except (ValueError, SyntaxError) as e:
                        pass

                # Extract hull vertices with myelin
                if 'hull_vertices_w_myel' in row and row['hull_vertices_w_myel']:
                    try:
                        # Parse the string representation of list of lists
                        hull_vertices_myel = ast.literal_eval(row['hull_vertices_w_myel'])

                        # Store each vertex atomically with composite key
                        for vertex_idx, vertex in enumerate(hull_vertices_myel):
                            if len(vertex) >= 2:
                                # Store X coordinate
                                x_value = float(vertex[0])
                                values_quant_x = ValuesQuant(
                                    value=x_value,
                                    object=csv_package_result.id,
                                    desc_inst=components['descriptors']['fiber-hull-vertex-with-myelin'].id,
                                    desc_quant=components['hull_vertex_x_myel_desc'].id,
                                    instance=sample_instance.id,
                                    value_blob={
                                        'value': x_value,
                                        'unit': 'um',
                                        'source': 'csv',
                                        'vertex_index': vertex_idx,
                                        'composite_key': f'hull_vertex_myel_{row_idx}_{vertex_idx}_x',
                                    },
                                )
                                values_quant_x.descriptors_inst = components['descriptors'][
                                    'fiber-hull-vertex-with-myelin'
                                ]
                                values_quant_x.descriptors_quant = components['hull_vertex_x_myel_desc']
                                values_quant_x.values_inst = sample_instance
                                values_quant_x.objects = csv_package_result
                                session.add(values_quant_x)
                                created_values['values_quant'].append(values_quant_x)

                                # Store Y coordinate
                                y_value = float(vertex[1])
                                values_quant_y = ValuesQuant(
                                    value=y_value,
                                    object=csv_package_result.id,
                                    desc_inst=components['descriptors']['fiber-hull-vertex-with-myelin'].id,
                                    desc_quant=components['hull_vertex_y_myel_desc'].id,
                                    instance=sample_instance.id,
                                    value_blob={
                                        'value': y_value,
                                        'unit': 'um',
                                        'source': 'csv',
                                        'vertex_index': vertex_idx,
                                        'composite_key': f'hull_vertex_myel_{row_idx}_{vertex_idx}_y',
                                    },
                                )
                                values_quant_y.descriptors_inst = components['descriptors'][
                                    'fiber-hull-vertex-with-myelin'
                                ]
                                values_quant_y.descriptors_quant = components['hull_vertex_y_myel_desc']
                                values_quant_y.values_inst = sample_instance
                                values_quant_y.objects = csv_package_result
                                session.add(values_quant_y)
                                created_values['values_quant'].append(values_quant_y)

                    except (ValueError, SyntaxError) as e:
                        pass

                # Extract boolean values using ValuesCat
                # Extract myelinated status
                if 'myelinated' in row and row['myelinated'] != '':
                    try:
                        # Convert string to boolean
                        is_myelinated = str(row['myelinated']).lower() in ['true', '1', 'yes']
                        term_to_use = components['terms']['true'] if is_myelinated else components['terms']['false']

                        values_cat = ValuesCat(
                            value_controlled=term_to_use.id,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-myelination-status'].id,
                            desc_cat=components['myelination_desc_cat'].id,
                            instance=sample_instance.id,
                        )
                        values_cat.controlled_terms = term_to_use
                        values_cat.objects = csv_package_result
                        values_cat.descriptors_inst_ = components['descriptors']['fiber-myelination-status']
                        values_cat.descriptors_cat = components['myelination_desc_cat']
                        values_cat.values_inst = sample_instance

                        get_or_create(session, values_cat)

                    except Exception as e:
                        pass

                # Extract chat status
                if 'chat' in row and row['chat'] != '':
                    try:
                        is_chat = str(row['chat']).lower() in ['true', '1', 'yes']
                        term_to_use = components['terms']['true'] if is_chat else components['terms']['false']

                        values_cat = ValuesCat(
                            value_controlled=term_to_use.id,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-chat-status'].id,
                            desc_cat=components['chat_desc_cat'].id,
                            instance=sample_instance.id,
                        )
                        values_cat.controlled_terms = term_to_use
                        values_cat.objects = csv_package_result
                        values_cat.descriptors_inst_ = components['descriptors']['fiber-chat-status']
                        values_cat.descriptors_cat = components['chat_desc_cat']
                        values_cat.values_inst = sample_instance

                        get_or_create(session, values_cat)

                    except Exception as e:
                        pass

                # Extract unmyelinated NF status
                if 'unmyel_nf' in row and row['unmyel_nf'] != '':
                    try:
                        is_unmyel_nf = str(row['unmyel_nf']).lower() in ['true', '1', 'yes']
                        term_to_use = components['terms']['true'] if is_unmyel_nf else components['terms']['false']

                        values_cat = ValuesCat(
                            value_controlled=term_to_use.id,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-unmyelinated-nf-status'].id,
                            desc_cat=components['unmyel_nf_desc_cat'].id,
                            instance=sample_instance.id,
                        )
                        values_cat.controlled_terms = term_to_use
                        values_cat.objects = csv_package_result
                        values_cat.descriptors_inst_ = components['descriptors']['fiber-unmyelinated-nf-status']
                        values_cat.descriptors_cat = components['unmyel_nf_desc_cat']
                        values_cat.values_inst = sample_instance

                        get_or_create(session, values_cat)

                    except Exception as e:
                        pass

                # Extract nav status
                if 'nav' in row and row['nav'] != '':
                    try:
                        is_nav = str(row['nav']).lower() in ['true', '1', 'yes']
                        term_to_use = components['terms']['true'] if is_nav else components['terms']['false']

                        values_cat = ValuesCat(
                            value_controlled=term_to_use.id,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-nav-status'].id,
                            desc_cat=components['nav_desc_cat'].id,
                            instance=sample_instance.id,
                        )
                        values_cat.controlled_terms = term_to_use
                        values_cat.objects = csv_package_result
                        values_cat.descriptors_inst_ = components['descriptors']['fiber-nav-status']
                        values_cat.descriptors_cat = components['nav_desc_cat']
                        values_cat.values_inst = sample_instance

                        get_or_create(session, values_cat)

                    except Exception as e:
                        pass

                # Extract rho (polar radius in micrometers)
                if 'rho' in row and row['rho']:
                    try:
                        rho_value = float(row['rho'])

                        values_quant = ValuesQuant(
                            value=rho_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-polar-coordinates'].id,
                            desc_quant=components['rho_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': rho_value, 'unit': 'um', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-polar-coordinates']
                        values_quant.descriptors_quant = components['rho_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract rho_pix (polar radius in pixels)
                if 'rho_pix' in row and row['rho_pix']:
                    try:
                        rho_pix_value = float(row['rho_pix'])

                        values_quant = ValuesQuant(
                            value=rho_pix_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-polar-coordinates'].id,
                            desc_quant=components['rho_pix_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': rho_pix_value, 'unit': 'pixels', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-polar-coordinates']
                        values_quant.descriptors_quant = components['rho_pix_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract phi (polar angle in radians)
                if 'phi' in row and row['phi']:
                    try:
                        phi_value = float(row['phi'])

                        values_quant = ValuesQuant(
                            value=phi_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-polar-coordinates'].id,
                            desc_quant=components['phi_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': phi_value, 'unit': 'radians', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-polar-coordinates']
                        values_quant.descriptors_quant = components['phi_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract threshold overlap percentage
                if 'th_overlap_p' in row and row['th_overlap_p']:
                    try:
                        th_overlap_value = float(row['th_overlap_p'])

                        values_quant = ValuesQuant(
                            value=th_overlap_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-threshold-overlap'].id,
                            desc_quant=components['th_overlap_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': th_overlap_value, 'unit': 'percent', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-threshold-overlap']
                        values_quant.descriptors_quant = components['th_overlap_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract c_estimate_nf (NF channel estimate)
                if 'c_estimate_nf' in row and row['c_estimate_nf']:
                    try:
                        c_estimate_nf_value = float(row['c_estimate_nf'])

                        values_quant = ValuesQuant(
                            value=c_estimate_nf_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-nf-channel-estimate'].id,
                            desc_quant=components['c_estimate_nf_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': c_estimate_nf_value, 'unit': 'dimensionless', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-nf-channel-estimate']
                        values_quant.descriptors_quant = components['c_estimate_nf_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract c_estimate_nf_frac (NF channel estimate fraction)
                if 'c_estimate_nf_frac' in row and row['c_estimate_nf_frac']:
                    try:
                        c_estimate_nf_frac_value = float(row['c_estimate_nf_frac'])

                        values_quant = ValuesQuant(
                            value=c_estimate_nf_frac_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-nf-channel-estimate'].id,
                            desc_quant=components['c_estimate_nf_frac_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': c_estimate_nf_frac_value, 'unit': 'fraction', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-nf-channel-estimate']
                        values_quant.descriptors_quant = components['c_estimate_nf_frac_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract c_estimate_nav (Nav channel estimate)
                if 'c_estimate_nav' in row and row['c_estimate_nav']:
                    try:
                        c_estimate_nav_value = float(row['c_estimate_nav'])

                        values_quant = ValuesQuant(
                            value=c_estimate_nav_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-nav-channel-estimate'].id,
                            desc_quant=components['c_estimate_nav_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': c_estimate_nav_value, 'unit': 'dimensionless', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-nav-channel-estimate']
                        values_quant.descriptors_quant = components['c_estimate_nav_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Extract c_estimate_nav_frac (Nav channel estimate fraction)
                if 'c_estimate_nav_frac' in row and row['c_estimate_nav_frac']:
                    try:
                        c_estimate_nav_frac_value = float(row['c_estimate_nav_frac'])

                        values_quant = ValuesQuant(
                            value=c_estimate_nav_frac_value,
                            object=csv_package_result.id,
                            desc_inst=components['descriptors']['fiber-nav-channel-estimate'].id,
                            desc_quant=components['c_estimate_nav_frac_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': c_estimate_nav_frac_value, 'unit': 'fraction', 'source': 'csv'},
                        )

                        values_quant.descriptors_inst = components['descriptors']['fiber-nav-channel-estimate']
                        values_quant.descriptors_quant = components['c_estimate_nav_frac_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = csv_package_result

                        session.add(values_quant)
                        created_values['values_quant'].append(values_quant)

                    except ValueError:
                        pass

                # Commit after processing each row
                if row_idx % 100 == 0:
                    session.commit()
                    print(f'  Processed {row_idx + 1} fibers...')

            # Final commit for remaining rows
            session.commit()
            print(f'  Completed processing {len(csv_data)} fibers from {csv_filename}')

    # If no CSV files were processed, add placeholder data
    if csv_file_count == 0 and package_idx > 0:
        print('\nNo CSV files found, using placeholder quantitative data')
        for idx, package in enumerate(package_objects):
            # Get corresponding parsed path
            for item in metadata['data']:
                if item.get('mimetype') == 'image/jpx' and item.get('dataset_relative_path'):
                    path_parts = pathlib.Path(item['dataset_relative_path']).parts
                    parsed_path = parse_path_structure(path_parts)
                    sample_key = f"{parsed_path['subject_id']}_{parsed_path['sample_id']}"

                    if sample_key in instances:
                        sample_instance = instances[sample_key]

                        # Create placeholder quantitative value
                        example_volume = 42.5 + idx
                        values_quant = ValuesQuant(
                            value=example_volume,
                            object=package.id,
                            desc_inst=components['descriptors']['nerve-volume'].id,
                            desc_quant=components['nerve_volume_desc'].id,
                            instance=sample_instance.id,
                            value_blob={'value': float(example_volume), 'unit': 'mm3', 'source': 'placeholder'},
                        )

                        # Set relationships
                        values_quant.descriptors_inst = components['descriptors']['nerve-volume']
                        values_quant.descriptors_quant = components['nerve_volume_desc']
                        values_quant.values_inst = sample_instance
                        values_quant.objects = package

                        session.add(values_quant)
                        session.commit()
                        created_values['values_quant'].append(values_quant)
                        print(f"Created placeholder volume for {parsed_path['sample_id']}: {example_volume} mm3")
                        break

    return created_values


def run_f006_ingestion(session=None, commit=False):
    """
    Main ingestion function for f006 dataset.

    This demonstrates a complete table-to-table ingestion using the ORM approach.
    """

    if session is None:
        session = get_session(echo=False, test=True)

    try:
        print(f'Starting F006 ingestion for dataset: {str(DATASET_UUID)}')

        # Load metadata
        metadata = load_path_metadata()
        print(f"Loaded metadata for {len(metadata['data'])} files")

        # Create CSV addresses for column headers
        csv_addresses = create_csv_addresses(session)
        print('Created CSV column header addresses')

        # Create necessary descriptors and components
        components = create_basic_descriptors(session)
        print('Created basic descriptors and components')

        # Ingest objects table
        dataset_obj, package_objects = ingest_objects_table(session, metadata, components)

        # Ingest instances table
        instances = ingest_instances_table(session, metadata, components, dataset_obj)

        # Create ObjDesc* mappings (intermediate tables)
        mappings = create_obj_desc_mappings(session, components, package_objects)

        # Create leaf table values using back_populate_tables
        leaf_values = create_leaf_values(
            session, metadata, components, dataset_obj, package_objects, instances, mappings
        )

        if commit:
            session.commit()
            print('✓ Transaction committed successfully')
        else:
            session.rollback()
            print('✓ Transaction rolled back (dry run)')

        print(f'✓ Ingestion completed successfully!')
        print(f'  - Dataset object: 1')
        print(f'  - Package objects: {len(package_objects)}')
        print(f'  - Instances: {len(instances)}')
        print(f"  - ObjDescInst mappings: {len(mappings['obj_desc_inst'])}")
        print(f"  - ObjDescCat mappings: {len(mappings['obj_desc_cat'])}")
        print(f"  - ObjDescQuant mappings: {len(mappings['obj_desc_quant'])}")
        print(f"  - ValuesCat entries: {len(leaf_values['values_cat'])}")
        print(f"  - ValuesQuant entries: {len(leaf_values['values_quant'])}")

        return {
            'dataset_obj': dataset_obj,
            'package_objects': package_objects,
            'instances': instances,
            'mappings': mappings,
            'leaf_values': leaf_values,
        }

    except Exception as e:
        session.rollback()
        print(f'✗ Ingestion failed: {e}')
        raise


if __name__ == '__main__':
    # Run the ingestion with commit=True for actual data insertion
    session = get_session(echo=True, test=True)
    result = run_f006_ingestion(session, commit=True)
    session.close()
    print('F006 ingestion completed!')
