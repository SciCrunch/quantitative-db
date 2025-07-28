#!/usr/bin/env python3
"""
Test to verify the ID matching fix for CSV files.
"""

import pathlib
import sys

# Add parent directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from ingestion.f006_csv_with_export import (
    parse_csv_path_structure,
    parse_jpx_path_structure,
)


def test_csv_id_construction():
    """Test that CSV paths now generate correct sample IDs."""
    print('=== Testing CSV ID Construction Fix ===\n')

    test_cases = [
        {
            'path': 'derivative/sub-f006/sam-l/site-l-seg-c2-A-L3/fasc-3/3_fibers.csv',
            'expected_sample_id': 'sam-l-seg-c2',
        },
        {
            'path': 'derivative/sub-f006/sam-r/site-r-seg-t5-B-L3/fasc-1/1_fibers.csv',
            'expected_sample_id': 'sam-r-seg-t5',
        },
        {
            'path': 'derivative/sub-f006/sam-l/site-l-seg-c10-A-L3/fasc-5/5_fibers.csv',
            'expected_sample_id': 'sam-l-seg-c10',
        },
    ]

    all_passed = True

    for test in test_cases:
        path = test['path']
        expected = test['expected_sample_id']

        path_parts = path.split('/')
        parsed = parse_csv_path_structure(path_parts)

        if parsed:
            actual = parsed['sample_id']
            passed = actual == expected
            all_passed &= passed

            print(f'Path: {path}')
            print(f'  Expected sample_id: {expected}')
            print(f'  Actual sample_id: {actual}')
            print(f"  Status: {'✓ PASS' if passed else '✗ FAIL'}")
            print(f'  Full parsed data: {parsed}\n')
        else:
            print(f'Failed to parse: {path}')
            all_passed = False

    # Also test that JPX parsing still works
    print('\n=== Verifying JPX Parsing Still Works ===\n')

    jpx_test = 'primary/sub-f006/sam-l/sam-l-seg-c2/B824_C2L_9um_1272_rec.jpx'
    jpx_parts = jpx_test.split('/')
    jpx_parsed = parse_jpx_path_structure(jpx_parts)

    print(f'JPX Path: {jpx_test}')
    print(f"  Parsed sample_id: {jpx_parsed['sample_id']}")
    print(f'  Full parsed data: {jpx_parsed}')

    jpx_correct = jpx_parsed['sample_id'] == 'sam-l-seg-c2'
    all_passed &= jpx_correct

    print(f"\n{'✓ All tests passed!' if all_passed else '✗ Some tests failed!'}")
    return all_passed


if __name__ == '__main__':
    test_csv_id_construction()
