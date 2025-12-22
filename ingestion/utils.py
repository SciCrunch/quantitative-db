#!/usr/bin/env python3
"""
Shared utilities for dataset ingestion.

This module provides common functions used across different dataset ingestion scripts.
"""

import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import yaml
from pennsieve import Pennsieve
from sqlalchemy.orm import Session

from quantdb.generic_ingest import get_or_create
from quantdb.models import (
    Addresses,
    Aspects,
    ControlledTerms,
    DescriptorsCat,
    DescriptorsInst,
    DescriptorsQuant,
    Objects,
    Units,
)


def load_yaml_mappings(*mapping_files: str) -> Dict[str, Any]:
    """
    Load and merge multiple YAML mapping files.

    Args:
        *mapping_files: Paths to YAML files to load and merge

    Returns:
        Merged dictionary of mappings
    """
    merged = {}

    for file_path in mapping_files:
        if pathlib.Path(file_path).exists():
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
                if data:
                    # Deep merge the dictionaries
                    merged = deep_merge(merged, data)

    return merged


def deep_merge(dict1: Dict, dict2: Dict) -> Dict:
    """
    Deep merge two dictionaries.

    Args:
        dict1: Base dictionary
        dict2: Dictionary to merge into dict1

    Returns:
        Merged dictionary
    """
    result = dict1.copy()

    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # For lists, extend rather than replace
            result[key].extend(value)
        else:
            result[key] = value

    return result


def parse_standard_path(path: str) -> Dict[str, str]:
    """
    Parse a standard SPARC/BIDS-like path structure.

    Expected patterns:
    - sub-{subject_id}/sam-{sample_id}/...
    - sub-{subject_id}/ses-{session_id}/...
    - derivatives/sub-{subject_id}/...

    Args:
        path: Path string to parse

    Returns:
        Dictionary with extracted IDs
    """
    result = {}

    # Extract subject ID
    sub_match = re.search(r'sub-([^/]+)', path)
    if sub_match:
        result['subject_id'] = f'sub-{sub_match.group(1)}'

    # Extract sample ID
    sam_match = re.search(r'sam-([^/]+)', path)
    if sam_match:
        result['sample_id'] = f'sam-{sam_match.group(1)}'

    # Extract session ID
    ses_match = re.search(r'ses-([^/]+)', path)
    if ses_match:
        result['session_id'] = f'ses-{ses_match.group(1)}'

    # Extract modality
    if 'microscopy' in path:
        result['modality'] = 'microscopy'
    elif 'ephys' in path:
        result['modality'] = 'electrophysiology'
    elif 'behavior' in path:
        result['modality'] = 'behavior'

    return result


def create_all_descriptors_from_yaml(session: Session, yaml_path: str, dataset_uuid: str) -> Dict[str, Any]:
    """
    Create all descriptors defined in a YAML file.

    Args:
        session: Database session
        yaml_path: Path to YAML file with descriptor definitions
        dataset_uuid: UUID of the dataset

    Returns:
        Dictionary of created descriptors and components
    """
    with open(yaml_path, 'r') as f:
        config = yaml.safe_load(f)

    components = {
        'aspects': {},
        'units': {},
        'descriptors_inst': {},
        'descriptors_quant': {},
        'descriptors_cat': {},
        'terms': {},
        'addresses': {},
    }

    # Create aspects
    if 'aspects' in config:
        for aspect_data in config['aspects']:
            aspect = Aspects(iri=aspect_data['iri'], label=aspect_data['label'])
            created = get_or_create(session, aspect)
            components['aspects'][aspect_data['label']] = created

    # Create units
    if 'units' in config:
        for unit_data in config['units']:
            unit = Units(iri=unit_data['iri'], label=unit_data['label'])
            created = get_or_create(session, unit)
            components['units'][unit_data['label']] = created

    # Create instance descriptors
    if 'descriptors' in config and 'instance_types' in config['descriptors']:
        for desc_data in config['descriptors']['instance_types']:
            desc = DescriptorsInst(iri=desc_data['iri'], label=desc_data['label'])
            created = get_or_create(session, desc)
            components['descriptors_inst'][desc_data['label']] = created

    # Create quantitative descriptors
    if 'descriptors' in config and 'quantitative' in config['descriptors']:
        for qd_data in config['descriptors']['quantitative']:
            # Look up referenced components
            domain_desc = components['descriptors_inst'].get(qd_data['domain'])
            aspect = components['aspects'].get(qd_data['aspect'])
            unit = components['units'].get(qd_data['unit'])

            if domain_desc and aspect and unit:
                qd = DescriptorsQuant(
                    shape=qd_data.get('shape', 'scalar'),
                    label=qd_data['label'],
                    aggregation_type=qd_data.get('aggregation_type', 'instance'),
                    unit=unit.id,
                    aspect=aspect.id,
                    domain=domain_desc.id,
                    description=qd_data.get('description', ''),
                )
                qd.units = unit
                qd.aspects = aspect
                qd.descriptors_inst = domain_desc

                created = get_or_create(session, qd)
                components['descriptors_quant'][qd_data['label']] = created

    # Create categorical descriptors
    if 'descriptors' in config and 'categorical' in config['descriptors']:
        for cd_data in config['descriptors']['categorical']:
            domain_desc = components['descriptors_inst'].get(cd_data['domain'])

            if domain_desc:
                cd = DescriptorsCat(
                    domain=domain_desc.id, range=cd_data.get('range', 'controlled'), label=cd_data['label']
                )
                cd.descriptors_inst = domain_desc

                created = get_or_create(session, cd)
                components['descriptors_cat'][cd_data['label']] = created

    # Create controlled terms
    if 'controlled_terms' in config:
        for term_data in config['controlled_terms']:
            term = ControlledTerms(iri=term_data['iri'], label=term_data['label'])
            created = get_or_create(session, term)
            components['terms'][term_data['label']] = created

    # Create addresses
    if 'addresses' in config:
        for addr_key, addr_data in config['addresses'].items():
            addr = Addresses(
                addr_type=addr_data['addr_type'],
                addr_field=addr_data.get('addr_field'),
                value_type=addr_data.get('value_type', 'single'),
            )
            created = get_or_create(session, addr)
            components['addresses'][addr_key] = created

    # Create standard addresses
    const_addr = get_or_create(session, Addresses(addr_type='constant', addr_field=None, value_type='single'))
    components['addresses']['constant'] = const_addr

    return components


def download_file_metadata(dataset_id: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Download file metadata from Pennsieve.

    Args:
        dataset_id: Pennsieve dataset ID
        output_path: Optional path to save metadata JSON

    Returns:
        Dictionary of file metadata
    """
    ps = Pennsieve()
    dataset = ps.get_dataset(dataset_id)

    metadata = {'dataset_id': dataset_id, 'dataset_name': dataset.name, 'data': []}

    # Walk through all files in dataset
    for item in dataset:
        if hasattr(item, 'files'):
            for file in item.files:
                file_info = {
                    'name': file.name,
                    'id': file.id,
                    'size': file.size,
                    'created': file.created_at.isoformat() if hasattr(file, 'created_at') else None,
                    'mimetype': getattr(file, 'type', 'application/octet-stream'),
                    'dataset_relative_path': f'{item.name}/{file.name}',
                }
                metadata['data'].append(file_info)

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(metadata, f, indent=2)

    return metadata


def create_standard_addresses(session: Session) -> Dict[str, Addresses]:
    """
    Create standard address types used across datasets.

    Args:
        session: Database session

    Returns:
        Dictionary of created addresses
    """
    addresses = {}

    # Constant address (no field)
    const_addr = Addresses(addr_type='constant', addr_field=None, value_type='single')
    addresses['constant'] = get_or_create(session, const_addr)

    # Tabular addresses
    tab_header = Addresses(addr_type='tabular-header', addr_field=None, value_type='single')
    addresses['tabular-header'] = get_or_create(session, tab_header)

    # JSON path address
    json_path = Addresses(addr_type='json-path', addr_field=None, value_type='single')
    addresses['json-path'] = get_or_create(session, json_path)

    return addresses


def read_csv_with_fallback(file_path: str, **kwargs) -> pd.DataFrame:
    """
    Read CSV file with multiple encoding fallbacks.

    Args:
        file_path: Path to CSV file
        **kwargs: Additional arguments for pd.read_csv

    Returns:
        Pandas DataFrame
    """
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']

    for encoding in encodings:
        try:
            return pd.read_csv(file_path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue

    # If all encodings fail, try with error handling
    return pd.read_csv(file_path, encoding='utf-8', errors='replace', **kwargs)


def normalize_column_name(name: str) -> str:
    """
    Normalize column names for consistent mapping.

    Args:
        name: Original column name

    Returns:
        Normalized column name
    """
    # Convert to lowercase
    normalized = name.lower()

    # Replace common separators with underscores
    normalized = re.sub(r'[\s\-\.]+', '_', normalized)

    # Remove special characters
    normalized = re.sub(r'[^\w_]', '', normalized)

    # Remove duplicate underscores
    normalized = re.sub(r'_+', '_', normalized)

    # Strip leading/trailing underscores
    normalized = normalized.strip('_')

    return normalized


def extract_numeric_value(value: Any) -> Optional[float]:
    """
    Extract numeric value from various formats.

    Args:
        value: Value to extract from (string, number, etc.)

    Returns:
        Float value or None if extraction fails
    """
    if pd.isna(value):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Remove common units and symbols
        cleaned = re.sub(r'[^\d\.\-\+eE]', '', value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                pass

    return None


def batch_create_objects(session: Session, objects: List[Any], batch_size: int = 1000) -> List[Any]:
    """
    Create multiple objects in batches for efficiency.

    Args:
        session: Database session
        objects: List of ORM objects to create
        batch_size: Number of objects per batch

    Returns:
        List of created objects
    """
    created_objects = []

    for i in range(0, len(objects), batch_size):
        batch = objects[i : i + batch_size]

        for obj in batch:
            result = get_or_create(session, obj)
            created_objects.append(result)

        # Commit after each batch
        session.commit()

    return created_objects


def download_csv_from_pennsieve(
    client: 'PennsieveClient', file_info: Dict[str, Any], cache_dir: Optional[pathlib.Path] = None
) -> Optional[pathlib.Path]:
    """
    Download a CSV file from Pennsieve with caching.

    Args:
        client: PennsieveClient instance
        file_info: File metadata dictionary
        cache_dir: Directory to cache downloaded files

    Returns:
        Path to the downloaded CSV file, or None if download failed
    """
    import requests

    # Ensure cache directory exists
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        cache_dir = pathlib.Path.cwd() / 'csv_cache'
        cache_dir.mkdir(parents=True, exist_ok=True)

    # Extract file info
    file_id = file_info.get('remote_inode_id', '')
    filename = file_info.get('name', pathlib.Path(file_info.get('dataset_relative_path', '')).name)
    cached_path = cache_dir / f'{file_id}_{filename}'

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
        response = requests.get(download_url, stream=True)
        response.raise_for_status()

        # Save to cache
        with open(cached_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f'Downloaded and cached: {cached_path} ({cached_path.stat().st_size:,} bytes)')
        return cached_path

    except Exception as e:
        print(f'Error downloading file: {e}')
        return None


def validate_dataset_structure(metadata: Dict[str, Any]) -> List[str]:
    """
    Validate dataset structure and return any issues.

    Args:
        metadata: Dataset metadata dictionary

    Returns:
        List of validation messages
    """
    issues = []

    # Check for required fields
    if 'data' not in metadata:
        issues.append("Missing 'data' field in metadata")
        return issues

    # Check file paths
    paths_seen = set()
    for item in metadata['data']:
        if 'dataset_relative_path' not in item:
            issues.append(f"Missing dataset_relative_path for file: {item.get('name', 'unknown')}")
            continue

        path = item['dataset_relative_path']
        if path in paths_seen:
            issues.append(f'Duplicate path found: {path}')
        paths_seen.add(path)

        # Check for standard structure
        if not re.search(r'sub-\w+', path):
            issues.append(f'Path missing subject identifier: {path}')

    return issues
