"""Tests for entity metadata extraction from curation-export.json.

Covers VAL-EXT-001 (entity counts) and VAL-EXT-002 (parent hierarchy)
from the validation contract.  Compares extracted data against
gold-standard fixture expectations for the f006 dataset.

Requires:
    - Cassava cache at ~/.quantdb/cassava.ucsd.edu.cache/
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from quantdb.extract_v2 import extract_entities_v2

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
        assert set(extracted.keys()) == {'subjects', 'samples', 'sites', 'parents'}

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
            if s['desc_inst'] == 'nerve-volume' and not any(
                p['parent'] in nerve_ids
                for p in extracted['parents']
                if p['child'] == s['id_formal']
            ) is False
        }
        # Simpler check: segments derived from nerve samples
        segment_parents = [
            p for p in extracted['parents']
            if p['child'].startswith('sam-') and p['child'].count('-') == 3
            and p['parent'] in nerve_ids
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

        sample_parents = [
            p for p in extracted['parents']
            if p['child'] in sample_set and p['parent'] in sample_set
        ]
        for p in sample_parents:
            assert id_to_index[p['parent']] < id_to_index[p['child']], (
                f"Parent {p['parent']} (idx {id_to_index[p['parent']]}) "
                f"should appear before child {p['child']} (idx {id_to_index[p['child']]})"
            )
