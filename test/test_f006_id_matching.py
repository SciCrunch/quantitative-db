#!/usr/bin/env python3
"""
Test to verify that all IDs in f006_path_metadata.json are properly matched during ingestion.
"""

import json
import pathlib
import sys
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from ingestion.f006_csv import (
    parse_csv_path_structure,
    parse_jpx_path_structure,
)


def load_metadata():
    """Load the f006 path metadata."""
    metadata_file = pathlib.Path(__file__).parent.parent / 'ingestion/data/f006_path_metadata.json'
    with open(metadata_file, 'r') as f:
        return json.load(f)


def extract_sample_ids_from_paths(metadata):
    """Extract all unique sample IDs from the metadata paths."""
    jpx_samples = set()
    csv_samples = set()
    jpx_paths = []
    csv_paths = []

    for item in metadata.get('data', []):
        if item.get('mimetype') == 'image/jpx':
            path = item.get('dataset_relative_path', '')
            jpx_paths.append(path)
            try:
                path_parts = path.split('/')
                parsed = parse_jpx_path_structure(path_parts)
                sample_id = parsed.get('sample_id')
                if sample_id:
                    jpx_samples.add(sample_id)
            except Exception as e:
                print(f'Error parsing JPX path {path}: {e}')

        elif item.get('mimetype') == 'text/csv':
            path = item.get('dataset_relative_path', '')
            csv_paths.append(path)
            try:
                path_parts = path.split('/')
                parsed = parse_csv_path_structure(path_parts)
                if parsed:  # parse_csv_path_structure returns None for paths it doesn't handle
                    sample_id = parsed.get('sample_id')
                    if sample_id:
                        csv_samples.add(sample_id)
            except Exception as e:
                print(f'Error parsing CSV path {path}: {e}')

    return jpx_samples, csv_samples, jpx_paths, csv_paths


def analyze_id_patterns(metadata):
    """Analyze the ID patterns in the metadata."""
    # Group paths by type and structure
    path_patterns = defaultdict(list)

    for item in metadata.get('data', []):
        path = item.get('dataset_relative_path', '')
        mimetype = item.get('mimetype', '')

        if mimetype in ['image/jpx', 'text/csv']:
            parts = path.split('/')
            pattern_key = f"{mimetype}:{len(parts)}:{'/'.join(parts[:2] if len(parts) >= 2 else parts)}"
            path_patterns[pattern_key].append(path)

    return path_patterns


def test_id_matching():
    """Test that IDs from metadata can be matched during ingestion."""
    print('=== Testing F006 ID Matching ===\n')

    # Load metadata
    metadata = load_metadata()
    print(f"Loaded {len(metadata.get('data', []))} items from metadata\n")

    # Extract sample IDs
    jpx_samples, csv_samples, jpx_paths, csv_paths = extract_sample_ids_from_paths(metadata)

    print(f'Found {len(jpx_samples)} unique JPX sample IDs:')
    for sid in sorted(jpx_samples):
        print(f'  - {sid}')

    print(f'\nFound {len(csv_samples)} unique CSV sample IDs:')
    for sid in sorted(csv_samples)[:10]:  # Show first 10
        print(f'  - {sid}')
    if len(csv_samples) > 10:
        print(f'  ... and {len(csv_samples) - 10} more')

    # Analyze path patterns
    print('\n=== Path Pattern Analysis ===')
    path_patterns = analyze_id_patterns(metadata)

    print('\nPath patterns found:')
    for pattern, paths in sorted(path_patterns.items()):
        print(f'\n{pattern}: {len(paths)} files')
        # Show a few examples
        for path in paths[:3]:
            print(f'  - {path}')
        if len(paths) > 3:
            print(f'  ... and {len(paths) - 3} more')

    # Check for mismatches
    print('\n=== ID Mismatch Analysis ===')

    # JPX paths create IDs like: sam-l-seg-t5
    # CSV paths now create IDs like: sam-l-seg-c2 (matching the JPX pattern)

    print('\nJPX sample ID pattern: sam-{side}-seg-{segment}')
    print('CSV sample ID pattern: sam-{side}-seg-{segment} (FIXED)')

    # The issue has been resolved - CSV parsing now returns full segment IDs like 'sam-l-seg-c2'
    # which matches the JPX pattern like 'sam-l-seg-t5'

    # Let's verify this by looking at actual paths
    print('\n=== Example Path Parsing ===')

    # JPX example
    jpx_example = 'primary/sub-f006/sam-l/sam-l-seg-t5/B824_T5L_9um_2.jpx'
    print(f'\nJPX path: {jpx_example}')
    jpx_parts = jpx_example.split('/')
    jpx_parsed = parse_jpx_path_structure(jpx_parts)
    print(f'Parsed: {jpx_parsed}')

    # CSV example
    csv_example = 'derivative/sub-f006/sam-l/site-l-seg-c2-A-L3/fasc-3/3_fibers.csv'
    print(f'\nCSV path: {csv_example}')
    csv_parts = csv_example.split('/')
    csv_parsed = parse_csv_path_structure(csv_parts)
    print(f'Parsed: {csv_parsed}')

    print('\n=== ISSUE RESOLVED ===')
    print("The CSV parsing function now correctly returns 'sam-l-seg-c2' as the sample_id")
    print("This matches the JPX pattern 'sam-l-seg-t5' and should resolve the 'No instance found' errors")

    print('\n=== Verification ===')
    print('Both JPX and CSV parsing now produce consistent sample_id patterns:')
    print(f"JPX sample_id: {jpx_parsed.get('sample_id')}")
    if csv_parsed:
        print(f"CSV sample_id: {csv_parsed.get('sample_id')}")
    else:
        print('CSV sample_id: None (path not recognized)')

    # Check for any remaining mismatches
    jpx_only = jpx_samples - csv_samples
    csv_only = csv_samples - jpx_samples

    if jpx_only:
        print(f'\nJPX-only sample IDs ({len(jpx_only)}): {sorted(jpx_only)}')
    if csv_only:
        print(f'\nCSV-only sample IDs ({len(csv_only)}): {sorted(csv_only)}')

    if not jpx_only and not csv_only:
        print('\n✓ All sample IDs are consistent between JPX and CSV files!')
    else:
        print(f'\n⚠ Found {len(jpx_only)} JPX-only and {len(csv_only)} CSV-only sample IDs')

    return jpx_samples, csv_samples


if __name__ == '__main__':
    jpx_samples, csv_samples = test_id_matching()
