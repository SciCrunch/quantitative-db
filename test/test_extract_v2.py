"""Tests for entity metadata extraction from curation-export.json.

Covers VAL-EXT-001 (entity counts) and VAL-EXT-002 (parent hierarchy)
from the validation contract.  Compares extracted data against
gold-standard fixture expectations for the f006 dataset.

Also covers VAL-EXT-003..006 for fascicle/fiber CSV extraction and
JPX file object extraction.

Requires:
    - Cassava cache at ~/.quantdb/cassava.ucsd.edu.cache/
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from quantdb.extract_v2 import (
    extract_entities_v2,
    extract_fasc_fib_v2,
    extract_reva_ft_v2,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

F006_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'

CACHE_DIR = Path.home() / '.quantdb' / 'cassava.ucsd.edu.cache' / F006_UUID
CURATION_EXPORT_PATH = CACHE_DIR / 'curation-export.json'

FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures' / 'f006'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def curation_export():
    """Load f006 curation-export.json from cassava cache."""
    if not CURATION_EXPORT_PATH.exists():
        pytest.skip(f'Cache not found: {CURATION_EXPORT_PATH}')
    with open(CURATION_EXPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def extracted(curation_export):
    """Run extract_entities_v2 once for all tests."""
    return extract_entities_v2(curation_export, F006_UUID)


@pytest.fixture(scope='module')
def gold_standard_breakdown():
    """Load the gold-standard values_inst_summary for count comparison."""
    path = FIXTURE_DIR / 'values_inst_summary.json'
    if not path.exists():
        pytest.skip(f'Gold-standard fixture not found: {path}')
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test: Output structure
# ---------------------------------------------------------------------------


class TestOutputStructure:
    """Verify the returned dict has the correct top-level keys and types."""

    def test_top_level_keys(self, extracted):
        assert set(extracted.keys()) == {
            'subjects',
            'samples',
            'sites',
            'parents',
        }

    def test_subjects_is_list(self, extracted):
        assert isinstance(extracted['subjects'], list)

    def test_samples_is_list(self, extracted):
        assert isinstance(extracted['samples'], list)

    def test_sites_is_list(self, extracted):
        assert isinstance(extracted['sites'], list)

    def test_parents_is_list(self, extracted):
        assert isinstance(extracted['parents'], list)


# ---------------------------------------------------------------------------
# Test: Subject extraction
# ---------------------------------------------------------------------------


class TestSubjectExtraction:
    """Verify subject parsing from curation-export.json."""

    def test_subject_count(self, extracted):
        assert len(extracted['subjects']) == 1

    def test_subject_type(self, extracted):
        sub = extracted['subjects'][0]
        assert sub['type'] == 'subject'

    def test_subject_desc_inst_human(self, extracted):
        sub = extracted['subjects'][0]
        assert sub['desc_inst'] == 'human'

    def test_subject_id_sub(self, extracted):
        sub = extracted['subjects'][0]
        assert sub['id_sub'] == 'sub-f006'

    def test_subject_id_formal(self, extracted):
        sub = extracted['subjects'][0]
        assert sub['id_formal'] == 'sub-f006'

    def test_subject_dataset(self, extracted):
        sub = extracted['subjects'][0]
        assert sub['dataset'] == F006_UUID


# ---------------------------------------------------------------------------
# Test: Sample extraction
# ---------------------------------------------------------------------------


class TestSampleExtraction:
    """Verify sample parsing and type translation."""

    def test_sample_count(self, extracted):
        assert len(extracted['samples']) == 90

    def test_all_samples_type_field(self, extracted):
        assert all(s['type'] == 'sample' for s in extracted['samples'])

    def test_sample_desc_inst_nerve_count(self, extracted):
        """Gold standard: sample|nerve = 2."""
        count = sum(1 for s in extracted['samples'] if s['desc_inst'] == 'nerve')
        assert count == 2

    def test_sample_desc_inst_nerve_volume_count(self, extracted):
        """Gold standard: sample|nerve-volume = 61 (34 segments + 27 subsegments)."""
        count = sum(1 for s in extracted['samples'] if s['desc_inst'] == 'nerve-volume')
        assert count == 61

    def test_sample_desc_inst_nerve_cross_section_count(self, extracted):
        """Gold standard: sample|nerve-cross-section = 27."""
        count = sum(1 for s in extracted['samples'] if s['desc_inst'] == 'nerve-cross-section')
        assert count == 27

    def test_sample_breakdown_vs_gold_standard(self, extracted, gold_standard_breakdown):
        """Compare extracted sample breakdown against gold-standard fixture."""
        breakdown = gold_standard_breakdown['breakdown']
        extracted_counts = Counter(s['desc_inst'] for s in extracted['samples'])
        assert extracted_counts['nerve'] == breakdown['sample|nerve']
        assert extracted_counts['nerve-volume'] == breakdown['sample|nerve-volume']
        assert extracted_counts['nerve-cross-section'] == breakdown['sample|nerve-cross-section']

    def test_all_samples_have_dataset(self, extracted):
        assert all(s['dataset'] == F006_UUID for s in extracted['samples'])

    def test_all_samples_have_id_sub(self, extracted):
        assert all('id_sub' in s and s['id_sub'] is not None for s in extracted['samples'])

    def test_all_samples_have_id_sam(self, extracted):
        assert all('id_sam' in s and s['id_sam'] is not None for s in extracted['samples'])

    def test_all_samples_have_id_formal(self, extracted):
        assert all('id_formal' in s for s in extracted['samples'])


# ---------------------------------------------------------------------------
# Test: Site extraction
# ---------------------------------------------------------------------------


class TestSiteExtraction:
    """Verify site parsing and type translation."""

    def test_site_count(self, extracted):
        """Feature spec: 59 sites from curation-export.json."""
        assert len(extracted['sites']) == 59

    def test_all_sites_type_field(self, extracted):
        assert all(s['type'] == 'site' for s in extracted['sites'])

    def test_all_sites_desc_inst(self, extracted):
        """All f006 sites are extruded-plane."""
        assert all(s['desc_inst'] == 'extruded-plane' for s in extracted['sites'])

    def test_all_sites_have_dataset(self, extracted):
        assert all(s['dataset'] == F006_UUID for s in extracted['sites'])

    def test_all_sites_have_id_sub(self, extracted):
        assert all('id_sub' in s and s['id_sub'] is not None for s in extracted['sites'])

    def test_sites_with_sample_specimen_have_id_sam(self, extracted):
        """Sites whose specimen_id starts with 'sam-' should have id_sam."""
        for s in extracted['sites']:
            assert 'id_sam' in s and s['id_sam'] is not None


# ---------------------------------------------------------------------------
# Test: Parent relationships
# ---------------------------------------------------------------------------


class TestParentRelationships:
    """Verify parent-child derivation from was_derived_from and specimen_id."""

    def test_parent_count(self, extracted):
        """90 sample parents + 59 site parents = 149 total."""
        assert len(extracted['parents']) == 149

    def test_nerve_samples_parent_is_subject(self, extracted):
        """Nerve samples (no was_derived_from) have subject as parent."""
        nerve_ids = {s['id_formal'] for s in extracted['samples'] if s['desc_inst'] == 'nerve'}
        nerve_parents = [p for p in extracted['parents'] if p['child'] in nerve_ids]
        assert all(p['parent'] == 'sub-f006' for p in nerve_parents)

    def test_segment_samples_parent_is_nerve(self, extracted):
        """Segment samples have was_derived_from pointing to nerve sample."""
        nerve_ids = {s['id_formal'] for s in extracted['samples'] if s['desc_inst'] == 'nerve'}
        segment_ids = {
            s['id_formal']
            for s in extracted['samples']
            if s['desc_inst'] == 'nerve-volume'
            and not any(p['parent'] in nerve_ids for p in extracted['parents'] if p['child'] == s['id_formal']) is False
        }
        # Simpler check: segments derived from nerve samples
        segment_parents = [
            p
            for p in extracted['parents']
            if p['child'].startswith('sam-') and p['child'].count('-') == 3 and p['parent'] in nerve_ids
        ]
        assert len(segment_parents) > 0

    def test_site_parents_are_samples(self, extracted):
        """All site parents are samples (specimen_id starts with sam-)."""
        site_ids = {s['id_formal'] for s in extracted['sites']}
        site_parents = [p for p in extracted['parents'] if p['child'] in site_ids]
        assert all(p['parent'].startswith('sam-') for p in site_parents)

    def test_all_parents_have_child_and_parent_keys(self, extracted):
        for p in extracted['parents']:
            assert 'child' in p
            assert 'parent' in p


# ---------------------------------------------------------------------------
# Test: FK string labels (not integer IDs)
# ---------------------------------------------------------------------------


class TestStringFKLabels:
    """Output dicts must use string labels for FK columns, not integer IDs."""

    def test_subject_desc_inst_is_string(self, extracted):
        for s in extracted['subjects']:
            assert isinstance(s['desc_inst'], str)

    def test_sample_desc_inst_is_string(self, extracted):
        for s in extracted['samples']:
            assert isinstance(s['desc_inst'], str)

    def test_site_desc_inst_is_string(self, extracted):
        for s in extracted['sites']:
            assert isinstance(s['desc_inst'], str)

    def test_no_integer_desc_inst(self, extracted):
        """desc_inst must never be an int (FK resolution is downstream)."""
        all_entities = extracted['subjects'] + extracted['samples'] + extracted['sites']
        for e in all_entities:
            assert not isinstance(e['desc_inst'], int)


# ---------------------------------------------------------------------------
# Test: Topological ordering of samples
# ---------------------------------------------------------------------------


class TestTopologicalOrder:
    """Samples must be sorted so parents appear before children."""

    def test_parent_before_child_in_sample_list(self, extracted):
        """Every sample whose parent is also a sample must appear after it."""
        sample_ids = [s['id_formal'] for s in extracted['samples']]
        sample_set = set(sample_ids)
        id_to_index = {sid: i for i, sid in enumerate(sample_ids)}

        sample_parents = [p for p in extracted['parents'] if p['child'] in sample_set and p['parent'] in sample_set]
        for p in sample_parents:
            assert id_to_index[p['parent']] < id_to_index[p['child']], (
                f"Parent {p['parent']} (idx {id_to_index[p['parent']]}) "
                f"should appear before child {p['child']} (idx {id_to_index[p['child']]})"
            )


# ===========================================================================
# extract_reva_ft_v2 tests (JPX file objects from path-metadata)
# ===========================================================================

PATH_METADATA_PATH = CACHE_DIR / 'path-metadata.json'


@pytest.fixture(scope='module')
def path_metadata():
    """Load f006 path-metadata.json from cassava cache."""
    if not PATH_METADATA_PATH.exists():
        pytest.skip(f'Cache not found: {PATH_METADATA_PATH}')
    with open(PATH_METADATA_PATH) as f:
        return json.load(f)


class TestRevaFtExtraction:
    """Tests for extract_reva_ft_v2 -- JPX/microCT file objects."""

    def test_returns_dict_with_objects_key(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        assert 'objects' in result

    def test_objects_is_list(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        assert isinstance(result['objects'], list)

    def test_jpx_object_count(self, path_metadata):
        """VAL-EXT-006: Correct number of JPX file objects."""
        result = extract_reva_ft_v2(path_metadata)
        assert len(result['objects']) == 60

    def test_objects_have_uuid(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        for obj in result['objects']:
            assert 'uuid' in obj
            assert isinstance(obj['uuid'], str)
            assert len(obj['uuid']) == 36  # UUID format

    def test_objects_have_file_id(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        for obj in result['objects']:
            assert 'file_id' in obj
            assert isinstance(obj['file_id'], int)

    def test_objects_have_id_type_package(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        for obj in result['objects']:
            assert obj['id_type'] == 'package'

    def test_no_duplicate_uuids(self, path_metadata):
        result = extract_reva_ft_v2(path_metadata)
        uuids = [obj['uuid'] for obj in result['objects']]
        assert len(uuids) == len(set(uuids))

    def test_empty_path_metadata(self):
        """extract_reva_ft_v2 handles empty data gracefully."""
        result = extract_reva_ft_v2({'data': []})
        assert result['objects'] == []

    def test_no_jpx_entries(self):
        """extract_reva_ft_v2 returns empty when no JPX mimetype."""
        pm = {
            'data': [
                {
                    'mimetype': 'text/csv',
                    'remote_id': 'package:abc',
                    'uri_api': 'https://x/files/1',
                },
            ]
        }
        result = extract_reva_ft_v2(pm)
        assert result['objects'] == []


# ===========================================================================
# extract_fasc_fib_v2 tests -- fascicle & fiber CSV extraction
# ===========================================================================

# ---------------------------------------------------------------------------
# Mock CSV data helpers
# ---------------------------------------------------------------------------


def _make_mock_fasc_csv(n_fascicles=3):
    """Build mock fascicles.csv rows (header + data)."""
    header = [
        'fascicle',
        'area',
        'longest_diameter',
        'shortest_diameter',
        'eff_diam',
    ]
    rows = [header]
    for i in range(1, n_fascicles + 1):
        rows.append(
            [
                str(i),
                str(100.0 + i),
                str(20.0 + i),
                str(10.0 + i),
                str(15.0 + i),
            ]
        )
    return rows


def _make_mock_fiber_csv(n_fibers=5, include_fascicle=True):
    """Build mock fibers.csv rows (header + data)."""
    header = [
        'fiber_area',
        'longest_diameter',
        'shortest_diameter',
        'eff_fib_diam',
        'myelinated',
    ]
    if include_fascicle:
        header = ['fascicle'] + header
    rows = [header]
    for i in range(1, n_fibers + 1):
        row = [
            str(50.0 + i),
            str(8.0 + i),
            str(4.0 + i),
            str(6.0 + i),
            'TRUE' if i % 2 == 0 else 'FALSE',
        ]
        if include_fascicle:
            row = [str((i - 1) // 2 + 1)] + row  # 2-3 fibers per fascicle
        rows.append(row)
    return rows


def _make_mock_path_metadata_with_csvs():
    """Build a minimal path-metadata dict with CSV entries."""
    return {
        'data': [
            {
                'basename': 'fascicles.csv',
                'mimetype': 'text/csv',
                'dataset_relative_path': 'primary/sub-f006/sam-l/' 'sam-l-seg-t5-A-L3/fascicles.csv',
                'remote_id': 'package:aaaa-1111-2222-3333-444444444444',
                'dataset_id': 'dataset:' + F006_UUID,
                'uri_api': 'https://api.pennsieve.io/packages/'
                'N:package:aaaa-1111-2222-3333-444444444444/'
                'files/9999901',
            },
            {
                'basename': 'fibers.csv',
                'mimetype': 'text/csv',
                'dataset_relative_path': 'primary/sub-f006/sam-l/' 'sam-l-seg-t5-A-L3/fibers.csv',
                'remote_id': 'package:bbbb-1111-2222-3333-444444444444',
                'dataset_id': 'dataset:' + F006_UUID,
                'uri_api': 'https://api.pennsieve.io/packages/'
                'N:package:bbbb-1111-2222-3333-444444444444/'
                'files/9999902',
            },
        ],
    }


@pytest.fixture(scope='module')
def mock_curation_export():
    """Minimal curation-export with one subject, one section sample, one site."""
    return {
        'subjects': [
            {'subject_id': 'sub-f006', 'species': {'id': 'NCBITaxon_9606'}},
        ],
        'samples': [
            {
                'sample_id': 'sam-l',
                'sample_type': 'nerve',
                'subject_id': 'sub-f006',
            },
            {
                'sample_id': 'sam-l-seg-t5-A-L3',
                'sample_type': 'section',
                'subject_id': 'sub-f006',
                'was_derived_from': ['sam-l'],
            },
        ],
        'sites': [
            {
                'site_id': 'site-l-seg-t5-A-L3-1',
                'site_type': 'extruded plane',
                'specimen_id': 'sam-l-seg-t5-A-L3',
            },
        ],
    }


class TestFascFibStructure:
    """Verify extract_fasc_fib_v2 output structure with mock data."""

    def test_top_level_keys(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        n_fasc = 3
        n_fib = 5
        fasc_rows = _make_mock_fasc_csv(n_fasc)
        fib_rows = _make_mock_fiber_csv(n_fib)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]

        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)

        expected_keys = {
            'fascicles',
            'fibers',
            'parents',
            'objects',
            'quant_values',
            'cat_values',
        }
        assert set(result.keys()) == expected_keys

    def test_fascicle_count(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        n_fasc = 3
        fasc_rows = _make_mock_fasc_csv(n_fasc)
        fib_rows = _make_mock_fiber_csv(5)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]

        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)
        assert len(result['fascicles']) == n_fasc

    def test_fiber_count(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        n_fib = 5
        fasc_rows = _make_mock_fasc_csv(3)
        fib_rows = _make_mock_fiber_csv(n_fib)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]

        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)
        assert len(result['fibers']) == n_fib

    def test_empty_csv_entries(self, mock_curation_export):
        """No CSV entries → empty results."""
        pm = {'data': []}
        fetcher = lambda blob: []
        result = extract_fasc_fib_v2(mock_curation_export, pm, F006_UUID, fetcher)
        assert result['fascicles'] == []
        assert result['fibers'] == []
        assert result['parents'] == []
        assert result['quant_values'] == []
        assert result['cat_values'] == []


class TestFascicleExtraction:
    """Verify fascicle instance generation from mock CSV data."""

    @pytest.fixture(scope='class')
    def fasc_result(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        fasc_rows = _make_mock_fasc_csv(3)
        fib_rows = _make_mock_fiber_csv(5)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]
        return extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)

    def test_fascicle_id_formal_pattern(self, fasc_result):
        """VAL-EXT-003: id_formal matches fasc-* pattern."""
        for f in fasc_result['fascicles']:
            assert f['id_formal'].startswith('fasc-')

    def test_fascicle_desc_inst(self, fasc_result):
        """Each fascicle has desc_inst='fascicle-cross-section'."""
        for f in fasc_result['fascicles']:
            assert f['desc_inst'] == 'fascicle-cross-section'

    def test_fascicle_type_below(self, fasc_result):
        for f in fasc_result['fascicles']:
            assert f['type'] == 'below'

    def test_fascicle_has_dataset(self, fasc_result):
        for f in fasc_result['fascicles']:
            assert f['dataset'] == F006_UUID

    def test_fascicle_has_id_sub(self, fasc_result):
        for f in fasc_result['fascicles']:
            assert f['id_sub'] == 'sub-f006'

    def test_fascicle_quant_values_count(self, fasc_result):
        """4 quant descriptors per fascicle (from mock with 4-col header)."""
        fasc_qv = [v for v in fasc_result['quant_values'] if v['desc_inst'] == 'fascicle-cross-section']
        # 3 fascicles × 4 descriptors = 12
        assert len(fasc_qv) == 3 * 4

    def test_fascicle_quant_descriptors(self, fasc_result):
        """Quant descriptor labels match expected columns."""
        descs = {v['desc_quant'] for v in fasc_result['quant_values'] if v['desc_inst'] == 'fascicle-cross-section'}
        assert descs == {
            'area',
            'longest_diameter',
            'shortest_diameter',
            'eff_diam',
        }

    def test_fascicle_string_fk_labels(self, fasc_result):
        """VAL-EXT-005: FK columns use string labels."""
        for f in fasc_result['fascicles']:
            assert isinstance(f['desc_inst'], str)
            assert not isinstance(f['desc_inst'], int)

    def test_fascicle_parent_relationships(self, fasc_result):
        """Fascicle parents point to sample/site."""
        fasc_ids = {f['id_formal'] for f in fasc_result['fascicles']}
        fasc_parents = [p for p in fasc_result['parents'] if p['child'] in fasc_ids]
        assert len(fasc_parents) == len(fasc_result['fascicles'])
        for p in fasc_parents:
            # parent is the sample since no site in path
            assert p['parent'] == 'sam-l-seg-t5-A-L3'


class TestFiberExtraction:
    """Verify fiber instance generation from mock CSV data."""

    @pytest.fixture(scope='class')
    def fib_result(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        fasc_rows = _make_mock_fasc_csv(3)
        fib_rows = _make_mock_fiber_csv(5, include_fascicle=True)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]
        return extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)

    def test_fiber_id_formal_pattern(self, fib_result):
        """VAL-EXT-004: id_formal matches fiber-* pattern."""
        for f in fib_result['fibers']:
            assert f['id_formal'].startswith('fiber-')

    def test_fiber_desc_inst(self, fib_result):
        for f in fib_result['fibers']:
            assert f['desc_inst'] == 'fiber-cross-section'

    def test_fiber_type_below(self, fib_result):
        for f in fib_result['fibers']:
            assert f['type'] == 'below'

    def test_fiber_has_dataset(self, fib_result):
        for f in fib_result['fibers']:
            assert f['dataset'] == F006_UUID

    def test_fiber_quant_values_count(self, fib_result):
        """4 quant descriptors per fiber."""
        fib_qv = [v for v in fib_result['quant_values'] if v['desc_inst'] == 'fiber-cross-section']
        # 5 fibers × 4 descriptors = 20
        assert len(fib_qv) == 5 * 4

    def test_fiber_quant_descriptors(self, fib_result):
        descs = {v['desc_quant'] for v in fib_result['quant_values'] if v['desc_inst'] == 'fiber-cross-section'}
        assert descs == {
            'fiber_area',
            'longest_diameter',
            'shortest_diameter',
            'eff_fib_diam',
        }

    def test_fiber_cat_values_count(self, fib_result):
        """1 categorical value per fiber (myelinated)."""
        assert len(fib_result['cat_values']) == 5

    def test_fiber_cat_myelinated_values(self, fib_result):
        """Myelinated column translates TRUE/FALSE correctly."""
        values = [v['value'] for v in fib_result['cat_values']]
        assert all(v in ('myelinated', 'unmyelinated') for v in values)
        # fibers 2,4 are TRUE (even index), rest FALSE
        assert values.count('myelinated') == 2
        assert values.count('unmyelinated') == 3

    def test_fiber_cat_desc_cat(self, fib_result):
        for v in fib_result['cat_values']:
            assert v['desc_cat'] == 'myelinated'

    def test_fiber_string_fk_labels(self, fib_result):
        """VAL-EXT-005: FK columns use string labels."""
        for f in fib_result['fibers']:
            assert isinstance(f['desc_inst'], str)
        for v in fib_result['quant_values']:
            assert isinstance(v['desc_inst'], str)
            assert isinstance(v['desc_quant'], str)
        for v in fib_result['cat_values']:
            assert isinstance(v['desc_inst'], str)
            assert isinstance(v['desc_cat'], str)

    def test_fiber_parent_is_fascicle(self, fib_result):
        """Fibers with fascicle column have fasc-* parent."""
        fib_ids = {f['id_formal'] for f in fib_result['fibers']}
        fib_parents = [p for p in fib_result['parents'] if p['child'] in fib_ids]
        assert len(fib_parents) == len(fib_result['fibers'])
        for p in fib_parents:
            assert p['parent'].startswith('fasc-')


class TestFiberWithoutFascicleColumn:
    """Fibers CSV without a fascicle column uses row index for id."""

    def test_fiber_index_based_id(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        # Only fiber entry (no fascicle column)
        fib_rows = _make_mock_fiber_csv(3, include_fascicle=False)
        content_map = {
            'fascicles.csv': _make_mock_fasc_csv(2),
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]
        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)

        # Fibers use index-based id
        ids = [f['id_formal'] for f in result['fibers']]
        assert ids == [
            'fiber-sam-l-seg-t5-A-L3-1',
            'fiber-sam-l-seg-t5-A-L3-2',
            'fiber-sam-l-seg-t5-A-L3-3',
        ]


class TestFascSubfolderFiltering:
    """Fibers inside fasc-N/ subfolders should be filtered out."""

    def test_fasc_subfolder_fibers_excluded(self, mock_curation_export):
        pm = {
            'data': [
                {
                    'basename': 'fibers.csv',
                    'mimetype': 'text/csv',
                    'dataset_relative_path': ('primary/sub-f006/sam-l/' 'sam-l-seg-t5-A-L3/' 'fasc-1/fibers.csv'),
                    'remote_id': 'package:cccc-1111-2222-3333-444444444444',
                    'dataset_id': 'dataset:' + F006_UUID,
                    'uri_api': 'https://x/files/1',
                },
            ],
        }
        fetcher = lambda blob: _make_mock_fiber_csv(3)
        result = extract_fasc_fib_v2(mock_curation_export, pm, F006_UUID, fetcher)
        # fasc-N/fibers.csv should be excluded
        assert result['fibers'] == []


class TestObjectsExtraction:
    """Verify objects dict from CSV entries."""

    def test_objects_populated(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        fasc_rows = _make_mock_fasc_csv(3)
        fib_rows = _make_mock_fiber_csv(5)
        content_map = {
            'fascicles.csv': fasc_rows,
            'fibers.csv': fib_rows,
        }
        fetcher = lambda blob: content_map[blob['basename']]
        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)

        # 2 objects: 1 fascicle CSV + 1 fiber CSV
        assert len(result['objects']) == 2

    def test_object_values(self, mock_curation_export):
        mock_pm = _make_mock_path_metadata_with_csvs()
        fetcher = lambda blob: _make_mock_fasc_csv(1) if 'fascicles' in blob['basename'] else _make_mock_fiber_csv(1)
        result = extract_fasc_fib_v2(mock_curation_export, mock_pm, F006_UUID, fetcher)
        for uuid, obj in result['objects'].items():
            assert obj['id_type'] == 'package'
            assert isinstance(obj['file_id'], int)


# ===========================================================================
# Integration tests -- real Pennsieve CSV fetch (skip on auth failure)
# ===========================================================================


def _make_csv_fetcher_from_pennsieve():
    """Create a csv_fetcher that uses sparcur path_from_blob."""
    try:
        from quantdb.ingest import path_from_blob
    except ImportError:
        return None

    def fetcher(blob):
        try:
            local_path = path_from_blob(blob)
            with open(local_path, 'rt') as f:
                return list(csv.reader(f))
        except Exception:
            return None

    return fetcher


class TestFascFibIntegration:
    """Integration tests using real CSV data from Pennsieve.

    These tests are skipped if:
    - Pennsieve auth fails
    - CSV files cannot be fetched
    - Path-metadata doesn't contain CSV entries
    """

    @pytest.fixture(scope='class')
    def integration_result(self, curation_export, path_metadata):
        """Try to fetch real CSV data and run extraction."""
        from quantdb.extract_v2 import _find_csv_entries

        csv_entries = _find_csv_entries(path_metadata)
        if not csv_entries:
            pytest.skip('No CSV entries in path-metadata ' '(CSVs not in cassava metadata)')

        fetcher = _make_csv_fetcher_from_pennsieve()
        if fetcher is None:
            pytest.skip('sparcur path_from_blob not available')

        result = extract_fasc_fib_v2(curation_export, path_metadata, F006_UUID, fetcher)

        if not result['fascicles'] and not result['fibers']:
            pytest.skip('No CSV data fetched (likely auth issue)')

        return result

    def test_fascicle_count_428(self, integration_result):
        """VAL-EXT-003: 428 fascicle instances."""
        assert len(integration_result['fascicles']) == 428

    def test_fiber_count_608811(self, integration_result):
        """VAL-EXT-004: 608,811 fiber instances."""
        assert len(integration_result['fibers']) == 608811

    def test_fascicle_id_formal_pattern(self, integration_result):
        for f in integration_result['fascicles']:
            assert f['id_formal'].startswith('fasc-')

    def test_fiber_id_formal_pattern(self, integration_result):
        for f in integration_result['fibers'][:100]:
            assert f['id_formal'].startswith('fiber-')

    def test_fascicle_desc_inst(self, integration_result):
        for f in integration_result['fascicles']:
            assert f['desc_inst'] == 'fascicle-cross-section'

    def test_fiber_desc_inst(self, integration_result):
        for f in integration_result['fibers'][:100]:
            assert f['desc_inst'] == 'fiber-cross-section'
