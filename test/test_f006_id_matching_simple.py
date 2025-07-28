#!/usr/bin/env python3
"""
Simple test to verify ID matching patterns in f006_path_metadata.json
"""

import json
import pathlib
from collections import defaultdict


def load_metadata():
    """Load the f006 path metadata."""
    metadata_file = pathlib.Path(__file__).parent.parent / 'ingestion/data/f006_path_metadata.json'
    with open(metadata_file, 'r') as f:
        return json.load(f)


def parse_jpx_path_simple(path):
    """Simple JPX path parser to extract IDs."""
    parts = path.split('/')
    if len(parts) >= 5 and parts[0] == 'primary':
        return {
            'subject': parts[1],  # sub-f006
            'sample_folder': parts[2],  # sam-l or sam-r
            'sample_id': parts[3],  # sam-l-seg-t5
            'filename': parts[4],
        }
    return None


def parse_csv_path_simple(path):
    """Simple CSV path parser to extract IDs."""
    parts = path.split('/')
    if len(parts) >= 6 and parts[0] == 'derivative':
        return {
            'subject': parts[1],  # sub-f006
            'sample_folder': parts[2],  # sam-l or sam-r
            'site': parts[3],  # site-l-seg-c2-A-L3
            'fascicle': parts[4],  # fasc-3
            'filename': parts[5],
        }
    return None


def main():
    print('=== F006 ID Matching Analysis ===\n')

    metadata = load_metadata()
    data = metadata.get('data', [])

    jpx_files = []
    csv_files = []

    for item in data:
        path = item.get('dataset_relative_path', '')
        mimetype = item.get('mimetype', '')

        if mimetype == 'image/jpx':
            jpx_files.append(path)
        elif mimetype == 'text/csv':
            csv_files.append(path)

    print(f'Found {len(jpx_files)} JPX files and {len(csv_files)} CSV files\n')

    # Parse JPX files
    jpx_samples = set()
    print('=== JPX Sample IDs ===')
    for path in jpx_files[:5]:  # Show first 5
        parsed = parse_jpx_path_simple(path)
        if parsed:
            jpx_samples.add(parsed['sample_id'])
            print(f'Path: {path}')
            print(f"  -> Sample ID: {parsed['sample_id']}\n")

    # Parse CSV files
    csv_sample_folders = set()
    csv_sites = defaultdict(set)
    print('\n=== CSV Path Structure ===')
    for path in csv_files[:5]:  # Show first 5
        parsed = parse_csv_path_simple(path)
        if parsed:
            csv_sample_folders.add(parsed['sample_folder'])
            csv_sites[parsed['sample_folder']].add(parsed['site'])
            print(f'Path: {path}')
            print(f"  -> Sample folder: {parsed['sample_folder']}")
            print(f"  -> Site: {parsed['site']}\n")

    # Show all unique JPX sample IDs
    print('\n=== All Unique JPX Sample IDs ===')
    all_jpx_samples = set()
    for path in jpx_files:
        parsed = parse_jpx_path_simple(path)
        if parsed:
            all_jpx_samples.add(parsed['sample_id'])

    for sid in sorted(all_jpx_samples):
        print(f'  - {sid}')

    # Show mapping between CSV sites and what they should map to
    print('\n=== CSV Site to JPX Sample Mapping ===')
    print('CSV sites contain segment info that should map to JPX samples:')
    print('\nFor sam-l:')
    for site in sorted(csv_sites.get('sam-l', []))[:10]:
        # Extract segment from site (e.g., site-l-seg-c2-A-L3 -> seg-c2)
        if 'seg-' in site:
            seg_part = site.split('seg-')[1].split('-')[0]
            expected_jpx_sample = f'sam-l-seg-{seg_part}'
            exists = expected_jpx_sample in all_jpx_samples
            print(f"  {site} -> {expected_jpx_sample} {'✓' if exists else '✗'}")

    print('\n=== ISSUE IDENTIFIED ===')
    print('The CSV files are organized by site (e.g., site-l-seg-c2-A-L3)')
    print('But the ingestion creates instances based on JPX sample IDs (e.g., sam-l-seg-c2)')
    print("\nThe f006.py parse_csv_path_structure() returns just 'sam-l' as sample_id")
    print("But it should construct 'sam-l-seg-c2' to match the JPX instances")

    print('\n=== SOLUTION ===')
    print('Modify parse_csv_path_structure() to extract the segment from the site')
    print('and construct a sample_id that matches the JPX pattern')
    print('\nExample fix:')
    print("  site: 'site-l-seg-c2-A-L3'")
    print("  extract: 'seg-c2'")
    print("  construct: 'sam-l-seg-c2'")


if __name__ == '__main__':
    main()
