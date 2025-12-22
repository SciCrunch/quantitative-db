#!/usr/bin/env python3
"""Test script to download a single CSV file using PennsieveClient"""

import json
import os
import sys
from pathlib import Path

# Add the parent directory to the Python path when running as a script
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent))

from quantdb.pennsieve_client import PennsieveClient


def test_download_single_csv():
    # Load metadata to find a CSV file
    # Get the parent directory of the test folder
    project_root = Path(__file__).parent.parent
    metadata_path = project_root / 'ingestion/data/reva_path_metadata.json'

    with open(metadata_path, 'r') as f:
        metadata = json.load(f)

    # Find the first CSV file
    csv_file = None
    for item in metadata['data']:
        if item.get('mimetype') == 'text/csv':
            csv_file = item
            break

    if not csv_file:
        print('No CSV files found in metadata')
        return

    print(f"Found CSV file: {csv_file['basename']}")
    print(f"Path: {csv_file['dataset_relative_path']}")
    print(f"Size: {csv_file['size_bytes']} bytes")
    print(f"URL: {csv_file['uri_api']}")

    # Initialize the client
    try:
        client = PennsieveClient()
        print('\nSuccessfully initialized PennsieveClient')
    except Exception as e:
        print(f'\nError initializing client: {e}')
        print('Make sure you have credentials set up at ~/.scicrunch/credentials/pennsieve')
        return

    # Try to download the file using the API URL
    try:
        print(f"\nAttempting to download from: {csv_file['uri_api']}")

        # The client's __get method can be used for direct URLs
        response = client._PennsieveClient__get(csv_file['uri_api'])

        # The response contains a JSON with the actual S3 URL
        s3_url_data = response.json()
        actual_url = s3_url_data.get('url')

        if not actual_url:
            print(f'No URL found in response: {s3_url_data}')
            return

        print(f'\nGot S3 presigned URL, downloading actual file...')

        # Download the actual file from S3
        import requests

        actual_response = requests.get(actual_url)
        actual_response.raise_for_status()

        # Save the content to a file
        output_path = Path(f"test_download_{csv_file['basename']}")
        output_path.write_bytes(actual_response.content)

        print(f'\nSuccessfully downloaded to: {output_path}')
        print(f'File size: {output_path.stat().st_size} bytes')
        print(f"Expected size: {csv_file['size_bytes']} bytes")

        # Show first few lines of the CSV
        print('\nFirst few lines of the CSV:')
        with open(output_path, 'r') as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                print(f'  {line.rstrip()}')

    except Exception as e:
        print(f'\nError downloading file: {e}')
        print(f'Error type: {type(e).__name__}')

        # Try alternative approach using package and file IDs
        try:
            print('\nTrying alternative download method...')

            # Extract package ID and file ID
            package_id = csv_file['remote_id']
            file_id = csv_file.get('file_id') or csv_file.get('remote_inode_id')

            print(f'Package ID: {package_id}')
            print(f'File ID: {file_id}')

            # Use the download manifest approach
            manifest = client.get_child_manifest(package_id)
            print(f'\nManifest response: {json.dumps(manifest, indent=2)[:500]}...')

        except Exception as e2:
            print(f'\nAlternative method also failed: {e2}')


if __name__ == '__main__':
    test_download_single_csv()
