#!/usr/bin/env python3
"""
Test script to download the first 5 CSV files from the F006 dataset using PennsieveClient.

This test is useful for:
1. Verifying Pennsieve credentials are working
2. Testing CSV download functionality without running full ingestion
3. Examining the structure and content of F006 CSV files
4. Ensuring the caching mechanism works properly
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add the parent directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from quantdb.pennsieve_client import PennsieveClient


def load_f006_metadata() -> Dict[str, Any]:
    """Load the F006 metadata file."""
    project_root = Path(__file__).parent.parent
    metadata_path = project_root / 'ingestion/data/f006_path_metadata.json'

    with open(metadata_path, 'r') as f:
        return json.load(f)


def find_csv_files(metadata: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    """Find CSV files in the metadata, specifically looking for fiber CSV files."""
    csv_files = []

    for item in metadata['data']:
        # Check mimetype and path since name might be 'unknown'
        if item.get('mimetype') == 'text/csv':
            path = item.get('dataset_relative_path', '')
            # Check if it's a fiber CSV by looking at the path
            if '_fibers.csv' in path or (path.startswith('derivative/') and path.endswith('.csv')):
                # Extract filename from path if name is unknown
                if item.get('name') == 'unknown' or not item.get('name'):
                    item['name'] = Path(path).name
                csv_files.append(item)
                if len(csv_files) >= limit:
                    break

    return csv_files


def download_csv_file(client: PennsieveClient, file_info: Dict[str, Any], cache_dir: Path) -> Path:
    """Download a single CSV file and cache it."""
    # Extract package ID from remote_id (format: package:uuid)
    remote_id = file_info.get('remote_id', '')
    if remote_id.startswith('package:'):
        package_id = remote_id.split(':', 1)[1]
    else:
        package_id = remote_id

    file_id = file_info.get('remote_inode_id', '')
    filename = file_info.get('name', file_info.get('basename', 'unknown.csv'))
    cached_path = cache_dir / f'{file_id}_{filename}'

    # Check if already cached
    if cached_path.exists():
        print(f'  ✓ Already cached: {cached_path.name}')
        return cached_path

    try:
        # First try using the API URL if available
        api_url = file_info.get('uri_api')
        if api_url:
            print(f'  → Using API URL: {api_url}')
            try:
                # Use the client's private method to get the download URL
                response = client._PennsieveClient__get(api_url)
                download_data = response.json()
                download_url = download_data.get('url')

                if download_url:
                    # Download the file directly
                    print(f'  ⬇ Downloading {filename}...')
                    import requests

                    actual_response = requests.get(download_url)
                    actual_response.raise_for_status()

                    # Save to cache
                    with open(cached_path, 'wb') as f:
                        f.write(actual_response.content)

                    print(f'  ✓ Downloaded: {cached_path.name} ({cached_path.stat().st_size:,} bytes)')
                    return cached_path
            except Exception as e:
                print(f'  ⚠ API URL method failed: {e}, trying manifest method...')

        # Fall back to manifest method
        manifest = client.get_child_manifest(package_id)
        if not manifest or 'data' not in manifest or not manifest['data']:
            print(f'  ✗ No manifest data for package {package_id}')
            return None

        # Find the specific file in the manifest by file_id
        file_data = None
        for item in manifest['data']:
            if str(item.get('id')) == str(file_id) or str(item.get('nodeId')) == str(file_id):
                file_data = item
                break

        # If not found by ID, try the first item (might be the only file)
        if not file_data and len(manifest['data']) > 0:
            file_data = manifest['data'][0]

        if not file_data:
            print(f'  ✗ File {file_id} not found in manifest')
            return None

        download_url = file_data.get('url')
        if not download_url:
            print(f'  ✗ No download URL in manifest')
            return None

        # Download the file
        print(f'  ⬇ Downloading {filename}...')
        import requests

        response = requests.get(download_url, stream=True)
        response.raise_for_status()

        # Save to cache
        with open(cached_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f'  ✓ Downloaded: {cached_path.name} ({cached_path.stat().st_size:,} bytes)')
        return cached_path

    except Exception as e:
        print(f'  ✗ Error downloading {filename}: {e}')
        return None


def analyze_csv_content(csv_path: Path) -> None:
    """Analyze and display CSV content."""
    import csv

    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            if not rows:
                print(f'    Empty CSV file')
                return

            # Show column headers
            headers = list(rows[0].keys())
            print(f"    Columns ({len(headers)}): {', '.join(headers[:5])}", end='')
            if len(headers) > 5:
                print(f' ... and {len(headers)-5} more')
            else:
                print()

            # Show row count and sample data
            print(f'    Rows: {len(rows)}')

            # Show sample values from first row
            if rows:
                print('    Sample data (first row):')
                for key in ['dNerve_um', 'NFasc', 'id_sub', 'id_sam', 'level']:
                    if key in rows[0]:
                        print(f'      {key}: {rows[0][key]}')

    except Exception as e:
        print(f'    Error reading CSV: {e}')


def test_download_first_5_csvs():
    """Main test function to download the first 5 CSV files from F006 dataset."""
    print('=' * 80)
    print('F006 CSV Download Test - First 5 Files')
    print('=' * 80)

    # Load metadata
    print('\n1. Loading F006 metadata...')
    try:
        metadata = load_f006_metadata()
        print(f"   ✓ Loaded metadata with {len(metadata['data'])} total files")
    except Exception as e:
        print(f'   ✗ Error loading metadata: {e}')
        return

    # Find CSV files
    print('\n2. Finding CSV files...')
    csv_files = find_csv_files(metadata, limit=5)
    print(f'   ✓ Found {len(csv_files)} fiber CSV files')

    if not csv_files:
        print('   ✗ No fiber CSV files found in metadata')
        return

    # Initialize Pennsieve client
    print('\n3. Initializing Pennsieve client...')
    try:
        client = PennsieveClient()
        print('   ✓ Successfully initialized PennsieveClient')
    except Exception as e:
        print(f'   ✗ Error initializing client: {e}')
        print('\n   To use this test, please set up Pennsieve credentials:')
        print('   1. Create ~/.scicrunch/credentials/pennsieve file')
        print('   2. Add PENNSIEVE_API_TOKEN=<your_token>')
        print('   3. Add PENNSIEVE_API_SECRET=<your_secret>')
        return

    # Set up cache directory
    project_root = Path(__file__).parent.parent
    cache_dir = project_root / 'ingestion/data/csv_cache' / '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f'\n4. Cache directory: {cache_dir}')

    # Download CSV files
    print('\n5. Downloading CSV files...')
    downloaded_files = []

    for i, csv_file in enumerate(csv_files, 1):
        print(f'\n   File {i}/{len(csv_files)}:')
        print(f"   Name: {csv_file.get('name', csv_file.get('basename', 'unknown'))}")
        print(f"   Path: {csv_file['dataset_relative_path']}")
        print(f"   Size: {csv_file['size_bytes']:,} bytes")
        print(f"   Package ID: {csv_file.get('remote_id', 'N/A')}")
        print(f"   File ID: {csv_file.get('remote_inode_id', 'N/A')}")

        csv_path = download_csv_file(client, csv_file, cache_dir)
        if csv_path:
            downloaded_files.append(csv_path)

            # Analyze the CSV content
            print('   Content analysis:')
            analyze_csv_content(csv_path)

    # Summary
    print('\n' + '=' * 80)
    print('DOWNLOAD SUMMARY')
    print('=' * 80)
    print(f'Successfully downloaded: {len(downloaded_files)}/{len(csv_files)} files')
    print(f'Cache location: {cache_dir}')

    if downloaded_files:
        print('\nDownloaded files:')
        for path in downloaded_files:
            print(f'  - {path.name}')

    return downloaded_files


if __name__ == '__main__':
    downloaded = test_download_first_5_csvs()
    print('\n✓ Test completed!')
