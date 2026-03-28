"""Unit tests for quantdb/extract_microct.py — MicroCT extraction module.

Tests verify: dict structure, key correctness, value ranges,
pixel conversion, FK label validity, id_formal naming conventions,
and hierarchy completeness.
"""
from __future__ import annotations

import textwrap

import pytest

from quantdb.extract_microct import (
    MICROCT_UUID,
    PIXEL_TO_UM,
    PIXEL_TO_UM2,
    classify_path_metadata_files,
    extract_microct_entities,
    extract_microct_objects,
    fetch_cassava_metadata,
    parse_data_wrapper,
    parse_fascicle_graphml,
    parse_nerve_morphology,
    parse_summary_morphology,
)

# ---------------------------------------------------------------------------
# Expected FK labels (must match inserts_microct.sql)
# ---------------------------------------------------------------------------

EXPECTED_NERVE_DESC_QUANT = {
    'nerve cross section area pixel-11um',
    'nerve cross section perimeter pixel-11um',
    'nerve cross section eq diameter pixel-11um',
    'nerve cross section centroid-x pixel-11um',
    'nerve cross section centroid-y pixel-11um',
    'nerve cross section major axis pixel-11um',
    'nerve cross section minor axis pixel-11um',
    'nerve cross section angle degree',
}

EXPECTED_FASCICLE_DESC_QUANT = {
    'fascicle cross section area pixel-11um',
    'fascicle cross section eq diameter pixel-11um',
    'fascicle cross section centroid-0 pixel-11um',
    'fascicle cross section centroid-1 pixel-11um',
    'fascicle cross section major axis pixel-11um',
    'fascicle cross section minor axis pixel-11um',
    'fascicle cross section angle degree',
}

EXPECTED_EDGE_DESC_CAT = {
    'fascicleEdgeIdentity',
    'fascicleEdgeSplit',
    'fascicleEdgeMerge',
}

EXPECTED_SUMMARY_DESC_QUANT = {
    'median nerve diameter mm',
    'sd nerve diameter mm',
    'median nerve area mm2',
    'sd nerve area mm2',
    'endoneurial area mm2',
    'fascicle count',
    'avg fascicle diameter mm',
    'sd fascicle diameter mm',
    'min fascicle diameter mm',
    'max fascicle diameter mm',
    'measurement distance mm',
    'measurement frame',
}


# ---------------------------------------------------------------------------
# Fixtures — sample data for unit tests
# ---------------------------------------------------------------------------

SAMPLE_NERVE_CSV = textwrap.dedent(
    """\
    index,area,perimeter,eq_diameter,center_x,center_y,major_axis,minor_axis,angle
    0,100,50.0,11.28,256.5,128.3,15.2,10.1,45.0
    1,,,,,,,,
    2,200,75.5,16.0,260.1,130.5,20.3,14.7,30.5
"""
)

SAMPLE_GRAPHML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <graphml xmlns="http://graphml.graphdrawing.org/xmlns">
      <key id="d0" for="node" attr.name="area" attr.type="int"/>
      <key id="d1" for="node" attr.name="equivalent_diameter" attr.type="double"/>
      <key id="d2" for="node" attr.name="centroid-0" attr.type="double"/>
      <key id="d3" for="node" attr.name="centroid-1" attr.type="double"/>
      <key id="d4" for="node" attr.name="ellipse_major_axis" attr.type="double"/>
      <key id="d5" for="node" attr.name="ellipse_minor_axis" attr.type="double"/>
      <key id="d6" for="node" attr.name="ellipse_angle" attr.type="double"/>
      <key id="d7" for="node" attr.name="frame" attr.type="int"/>
      <key id="d8" for="edge" attr.name="identity" attr.type="boolean"/>
      <key id="d9" for="edge" attr.name="split" attr.type="boolean"/>
      <key id="d10" for="edge" attr.name="merge" attr.type="boolean"/>
      <graph id="G" edgedefault="directed">
        <node id="0">
          <data key="d0">50</data>
          <data key="d1">7.98</data>
          <data key="d2">100.5</data>
          <data key="d3">200.3</data>
          <data key="d4">12.0</data>
          <data key="d5">8.0</data>
          <data key="d6">25.0</data>
          <data key="d7">0</data>
        </node>
        <node id="1">
          <data key="d0">60</data>
          <data key="d1">8.74</data>
          <data key="d2">110.2</data>
          <data key="d3">205.1</data>
          <data key="d4">13.5</data>
          <data key="d5">9.2</data>
          <data key="d6">30.0</data>
          <data key="d7">1</data>
        </node>
        <node id="2">
          <data key="d0">55</data>
          <data key="d1">8.36</data>
          <data key="d2">105.0</data>
          <data key="d3">202.0</data>
          <data key="d4">12.5</data>
          <data key="d5">8.5</data>
          <data key="d6">27.5</data>
          <data key="d7">1</data>
        </node>
        <edge source="0" target="1">
          <data key="d8">true</data>
          <data key="d9">false</data>
          <data key="d10">false</data>
        </edge>
        <edge source="0" target="2">
          <data key="d8">false</data>
          <data key="d9">true</data>
          <data key="d10">false</data>
        </edge>
      </graph>
    </graphml>
"""
)

SAMPLE_BRANCH_CSV = textwrap.dedent(
    """\
    subject,sample,branch_name,interlex_id,median_nerve_diam_mm,sd_nerve_diam_mm,median_nerve_area_mm2,sd_nerve_area_mm2,endo_area_mm2,num_fas,avg_fas_diam_mm,sd_fas_diam_mm,min_fas_diam_mm,max_fas_diam_mm,measurement_dist_mm,measurement_frame,target
    SR042,CL1,left_cervical_cardiac_branch,ILX:12345,0.5,0.1,0.196,0.05,0.12,3,0.15,0.03,0.1,0.2,5.0,42,cardiac
    SR042,CL2,left_superior_laryngeal_nerve,ILX:67890,0.8,0.15,0.503,0.08,0.35,5,0.22,0.04,0.15,0.3,8.2,67,laryngeal
"""
)

SAMPLE_CRANIAL_CSV = textwrap.dedent(
    """\
    subject,sample,nerve_name,interlex_id,median_nerve_diam_mm,sd_nerve_diam_mm,median_nerve_area_mm2,sd_nerve_area_mm2,endo_area_mm2,num_fas,avg_fas_diam_mm,sd_fas_diam_mm,min_fas_diam_mm,max_fas_diam_mm,measurement_dist_mm,measurement_frame,target
    SR042,CL1,left_hypoglossal_nerve,ILX:11111,0.7,0.12,0.385,0.06,0.28,4,0.18,0.035,0.12,0.25,3.5,30,motor
"""
)

SAMPLE_WRAPPER_JSON = textwrap.dedent(
    """\
    {
        "description": {
            "modality": "microct",
            "subject_id": "SR042",
            "sample_id": "CL1"
        },
        "pixel_properties": {
            "dim": 3,
            "body_axis_order": "RPI",
            "dim_order": "ZYX",
            "pixel_type": "int16",
            "size_x": 2048,
            "size_y": 2048,
            "size_z": 5000,
            "physical_size_x": 11.4,
            "physical_size_y": 11.4,
            "physical_size_z": 11.4,
            "physical_size_x_unit": "um",
            "physical_size_y_unit": "um",
            "physical_size_z_unit": "um"
        },
        "annotations": {},
        "transforms": {}
    }
"""
)


# ---------------------------------------------------------------------------
# Curation-export fixture (minimal structure for entity extraction tests)
# ---------------------------------------------------------------------------

SAMPLE_CURATION_EXPORT = {
    'subjects': [
        {
            'subject_id': 'sub-SR042',
            'species': {'id': 'NCBITaxon:9606', 'label': 'Homo sapiens'},
            'age': {'magnitude': 36, 'type': 'quantity', 'units': 'year'},
            'sex': 'Male',
        }
    ],
    'samples': [
        {
            'sample_id': 'sam-SR042-CL1',
            'subject_id': 'sub-SR042',
            'sample_type': 'Tissue',
        },
        {
            'sample_id': 'sam-SR042-CL2',
            'subject_id': 'sub-SR042',
            'sample_type': 'Tissue',
        },
        {
            'sample_id': 'sam-SR042-CR1',
            'subject_id': 'sub-SR042',
            'sample_type': 'Tissue',
        },
    ],
    'sites': [],
}


# ===================================================================
# Tests: fetch_cassava_metadata (requires network)
# ===================================================================


class TestFetchCassavaMetadata:
    """VAL-EXTRACT-001: Cassava fetch returns valid data."""

    def test_fetch_returns_valid_curation_export(self):
        ce, pm = fetch_cassava_metadata(MICROCT_UUID)
        assert 'subjects' in ce
        assert 'samples' in ce
        assert isinstance(ce['subjects'], list)
        assert isinstance(ce['samples'], list)
        assert len(ce['subjects']) > 0
        assert len(ce['samples']) > 0

    def test_fetch_returns_valid_path_metadata(self):
        ce, pm = fetch_cassava_metadata(MICROCT_UUID)
        assert 'data' in pm
        assert isinstance(pm['data'], list)
        assert len(pm['data']) > 0


# ===================================================================
# Tests: extract_microct_entities
# ===================================================================


class TestExtractMicroctEntities:
    """VAL-EXTRACT-002, VAL-EXTRACT-003: Entity extraction."""

    def test_subjects_extracted(self):
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        vis = result['values_inst']
        subjects = [v for v in vis if v['type'] == 'subject']
        assert len(subjects) == 1
        sub = subjects[0]
        assert sub['id_formal'] == 'sub-SR042'
        assert sub['dataset'] == MICROCT_UUID
        assert sub['desc_inst'] == 'human'
        assert sub['id_sub'] == 'sub-SR042'

    def test_samples_extracted(self):
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        vis = result['values_inst']
        samples = [v for v in vis if v['type'] == 'sample']
        assert len(samples) == 3
        for s in samples:
            assert s['dataset'] == MICROCT_UUID
            assert s['desc_inst'] == 'tissue'
            assert s['type'] == 'sample'
            assert s['id_sub'] == 'sub-SR042'
            assert s['id_formal'].startswith('sam-')

    def test_values_inst_keys(self):
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        required_keys = {'dataset', 'id_formal', 'type', 'desc_inst', 'id_sub'}
        for vi in result['values_inst']:
            assert required_keys.issubset(vi.keys())

    def test_parent_relationships(self):
        """Every sample has a parent edge pointing to its subject."""
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        parents = result['instance_parent']
        assert len(parents) == 3  # one per sample

        sample_ids = {v['id_formal'] for v in result['values_inst'] if v['type'] == 'sample'}
        for p in parents:
            assert p['child'] in sample_ids
            assert p['parent'] == 'sub-SR042'

    def test_parent_edges_reference_valid_ids(self):
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        all_ids = {v['id_formal'] for v in result['values_inst']}
        for p in result['instance_parent']:
            assert p['child'] in all_ids, f"Child {p['child']} not in values_inst"
            assert p['parent'] in all_ids, f"Parent {p['parent']} not in values_inst"

    def test_id_formal_naming(self):
        result = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        subjects = [v for v in result['values_inst'] if v['type'] == 'subject']
        samples = [v for v in result['values_inst'] if v['type'] == 'sample']
        for sub in subjects:
            assert sub['id_formal'].startswith('sub-')
        for sam in samples:
            assert sam['id_formal'].startswith('sam-')


# ===================================================================
# Tests: parse_nerve_morphology
# ===================================================================


class TestParseNerveMorphology:
    """VAL-EXTRACT-004: NerveMorphology CSV parsing."""

    def setup_method(self):
        self.obj_uuid = 'test-object-uuid'
        self.nerve_id = 'nerve-SR042-CL1-left_cervical_trunk'
        self.result = parse_nerve_morphology(
            SAMPLE_NERVE_CSV,
            self.obj_uuid,
            MICROCT_UUID,
            self.nerve_id,
        )

    def test_returns_list(self):
        assert isinstance(self.result, list)

    def test_blank_row_skipped(self):
        """Row with index=1 is blank and should be skipped."""
        # 2 non-blank rows × 8 columns = 16 dicts
        assert len(self.result) == 16

    def test_dict_structure(self):
        required_keys = {
            'value',
            'value_blob',
            'object',
            'desc_inst',
            'desc_quant',
            'instance',
        }
        for d in self.result:
            assert required_keys.issubset(d.keys()), f'Missing keys: {required_keys - d.keys()}'

    def test_instance_structure(self):
        for d in self.result:
            inst = d['instance']
            assert 'dataset' in inst
            assert 'id_formal' in inst
            assert inst['dataset'] == MICROCT_UUID

    def test_desc_inst_is_nerve_cross_section(self):
        for d in self.result:
            assert d['desc_inst'] == 'nerve-cross-section'

    def test_desc_quant_labels_valid(self):
        labels = {d['desc_quant'] for d in self.result}
        assert labels.issubset(EXPECTED_NERVE_DESC_QUANT)
        # All 8 columns should be present
        assert labels == EXPECTED_NERVE_DESC_QUANT

    def test_values_stored_as_raw_pixels(self):
        """Values are stored in pixel-11um units (raw pixel values)."""
        # First row: area=100 pixels → stored as 100.0
        area_dicts = [d for d in self.result if d['desc_quant'] == 'nerve cross section area pixel-11um']
        assert len(area_dicts) == 2
        # Row 0: area=100
        row0_area = [d for d in area_dicts if '-slice-0' in d['instance']['id_formal']]
        assert len(row0_area) == 1
        assert row0_area[0]['value'] == 100.0

    def test_angle_stored_as_degrees(self):
        angle_dicts = [d for d in self.result if d['desc_quant'] == 'nerve cross section angle degree']
        assert len(angle_dicts) == 2
        values = sorted(d['value'] for d in angle_dicts)
        assert values == [30.5, 45.0]

    def test_value_blob_equals_value(self):
        for d in self.result:
            assert d['value'] == d['value_blob']

    def test_object_uuid_set(self):
        for d in self.result:
            assert d['object'] == self.obj_uuid

    def test_id_formal_pattern(self):
        """Instance id_formals follow nerve-...-slice-N pattern."""
        id_formals = {d['instance']['id_formal'] for d in self.result}
        for idf in id_formals:
            assert idf.startswith(self.nerve_id)
            assert '-slice-' in idf

    def test_no_blank_row_values(self):
        """No values should come from the blank row (index=1)."""
        for d in self.result:
            assert '-slice-1' not in d['instance']['id_formal']


# ===================================================================
# Tests: parse_fascicle_graphml
# ===================================================================


class TestParseFascicleGraphml:
    """VAL-EXTRACT-005, VAL-EXTRACT-006: GraphML parsing."""

    def setup_method(self):
        self.obj_uuid = 'test-graphml-uuid'
        self.nerve_id = 'nerve-SR042-CL1-left_cervical_trunk'
        self.result = parse_fascicle_graphml(
            SAMPLE_GRAPHML,
            self.obj_uuid,
            MICROCT_UUID,
            self.nerve_id,
        )

    def test_returns_dict_with_expected_keys(self):
        assert isinstance(self.result, dict)
        expected_keys = {
            'values_inst',
            'instance_parent',
            'values_quant',
            'values_cat',
        }
        assert set(self.result.keys()) == expected_keys

    def test_fascicle_instances_created(self):
        """3 nodes → 3 fascicle instances."""
        vis = self.result['values_inst']
        assert len(vis) == 3
        for vi in vis:
            assert vi['desc_inst'] == 'fascicle-cross-section'
            assert vi['type'] == 'below'
            assert vi['dataset'] == MICROCT_UUID

    def test_fascicle_instance_id_formal(self):
        vis = self.result['values_inst']
        for vi in vis:
            assert vi['id_formal'].startswith(self.nerve_id)
            assert '-fasc-' in vi['id_formal']

    def test_parent_links_for_each_fascicle(self):
        """Each fascicle has a parent link to a nerve slice."""
        ips = self.result['instance_parent']
        assert len(ips) == 3
        for ip in ips:
            assert ip['child'].startswith(self.nerve_id)
            assert '-fasc-' in ip['child']
            assert '-slice-' in ip['parent']

    def test_node_measurements_count(self):
        """3 nodes × 7 measurements = 21 values_quant."""
        vq = self.result['values_quant']
        assert len(vq) == 21

    def test_node_measurement_keys(self):
        required_keys = {
            'value',
            'value_blob',
            'object',
            'desc_inst',
            'desc_quant',
            'instance',
        }
        for d in self.result['values_quant']:
            assert required_keys.issubset(d.keys())

    def test_node_desc_quant_labels(self):
        labels = {d['desc_quant'] for d in self.result['values_quant']}
        assert labels.issubset(EXPECTED_FASCICLE_DESC_QUANT)
        assert labels == EXPECTED_FASCICLE_DESC_QUANT

    def test_node_values_stored_raw(self):
        """Values stored as raw pixel values."""
        area_dicts = [
            d for d in self.result['values_quant'] if d['desc_quant'] == 'fascicle cross section area pixel-11um'
        ]
        assert len(area_dicts) == 3
        values = sorted(d['value'] for d in area_dicts)
        assert values == [50.0, 55.0, 60.0]

    def test_edge_categorical_values(self):
        """2 edges × 3 properties = 6 values_cat."""
        vc = self.result['values_cat']
        assert len(vc) == 6

    def test_edge_desc_cat_labels(self):
        labels = {d['desc_cat'] for d in self.result['values_cat']}
        assert labels == EXPECTED_EDGE_DESC_CAT

    def test_edge_controlled_values(self):
        """Edge values are 'true' or 'false'."""
        for d in self.result['values_cat']:
            assert d['value_controlled'] in ('true', 'false')

    def test_edge_instance_references_source_node(self):
        """Edge values reference the source node's fascicle."""
        vc = self.result['values_cat']
        for d in vc:
            idf = d['instance']['id_formal']
            assert '-fasc-' in idf

    def test_hierarchy_completeness(self):
        """Every fascicle instance has a parent link."""
        vi_ids = {vi['id_formal'] for vi in self.result['values_inst']}
        ip_children = {ip['child'] for ip in self.result['instance_parent']}
        assert vi_ids == ip_children


# ===================================================================
# Tests: parse_summary_morphology
# ===================================================================


class TestParseSummaryMorphology:
    """VAL-EXTRACT-007: Summary morphology CSV parsing."""

    def test_branch_morphology_parsing(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        assert 'values_quant' in result
        assert 'values_inst' in result
        assert 'instance_parent' in result

    def test_branch_values_count(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        # 2 rows × 12 columns = 24 values
        assert len(result['values_quant']) == 24

    def test_branch_instances(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        assert len(result['values_inst']) == 2
        for vi in result['values_inst']:
            assert vi['desc_inst'] == 'nerve'
            assert vi['id_formal'].startswith('summary-')

    def test_branch_parent_links(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        assert len(result['instance_parent']) == 2
        for ip in result['instance_parent']:
            assert ip['parent'].startswith('sam-SR042-')

    def test_cranial_nerves_parsing(self):
        result = parse_summary_morphology(
            SAMPLE_CRANIAL_CSV,
            'test-cranial-uuid',
            MICROCT_UUID,
        )
        assert len(result['values_quant']) == 12
        assert len(result['values_inst']) == 1

    def test_values_mm_stored_as_is(self):
        """Values are already in mm/mm2 and should be stored as-is."""
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        diam_dicts = [d for d in result['values_quant'] if d['desc_quant'] == 'median nerve diameter mm']
        values = sorted(d['value'] for d in diam_dicts)
        assert values == [0.5, 0.8]

    def test_desc_quant_labels_valid(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        labels = {d['desc_quant'] for d in result['values_quant']}
        assert labels.issubset(EXPECTED_SUMMARY_DESC_QUANT)

    def test_values_quant_dict_structure(self):
        result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'test-branch-uuid',
            MICROCT_UUID,
        )
        required_keys = {
            'value',
            'value_blob',
            'object',
            'desc_inst',
            'desc_quant',
            'instance',
        }
        for d in result['values_quant']:
            assert required_keys.issubset(d.keys())
            assert d['desc_inst'] == 'nerve'


# ===================================================================
# Tests: parse_data_wrapper
# ===================================================================


class TestParseDataWrapper:
    """parse_data_wrapper tests."""

    def test_returns_metadata(self):
        result = parse_data_wrapper(
            SAMPLE_WRAPPER_JSON,
            'test-wrapper-uuid',
        )
        assert result['subject_id'] == 'SR042'
        assert result['sample_id'] == 'CL1'
        assert result['modality'] == 'microct'
        assert result['object_uuid'] == 'test-wrapper-uuid'

    def test_pixel_properties(self):
        result = parse_data_wrapper(
            SAMPLE_WRAPPER_JSON,
            'test-wrapper-uuid',
        )
        pp = result['pixel_properties']
        assert pp['dim'] == 3
        assert pp['size_x'] == 2048
        assert pp['size_z'] == 5000
        assert pp['physical_size_x'] == 11.4


# ===================================================================
# Tests: extract_microct_objects
# ===================================================================


class TestExtractMicroctObjects:
    """Object extraction from path-metadata."""

    def test_extracts_package_objects(self):
        pm = {
            'data': [
                {
                    'remote_id': 'package:aaaa-bbbb-cccc',
                    'uri_api': 'https://api.example/file/12345',
                    'basename': 'test.csv',
                },
                {
                    'remote_id': 'collection:xxxx-yyyy',
                    'basename': 'folder',
                },
                {
                    'remote_id': 'package:dddd-eeee-ffff',
                    'file_id': 67890,
                    'basename': 'test2.graphml',
                },
            ],
        }
        result = extract_microct_objects(pm)
        objs = result['objects']
        # Only packages, not collections
        assert len(objs) == 2

    def test_object_structure(self):
        pm = {
            'data': [
                {
                    'remote_id': 'package:aaaa-bbbb',
                    'file_id': 123,
                    'basename': 'file.csv',
                }
            ],
        }
        result = extract_microct_objects(pm)
        obj = result['objects'][0]
        assert obj['uuid'] == 'aaaa-bbbb'
        assert obj['file_id'] == 123
        assert obj['id_type'] == 'package'

    def test_deduplication(self):
        pm = {
            'data': [
                {
                    'remote_id': 'package:same-uuid',
                    'file_id': 1,
                    'basename': 'a.csv',
                },
                {
                    'remote_id': 'package:same-uuid',
                    'file_id': 1,
                    'basename': 'a.csv',
                },
            ],
        }
        result = extract_microct_objects(pm)
        assert len(result['objects']) == 1


# ===================================================================
# Tests: classify_path_metadata_files
# ===================================================================


class TestClassifyPathMetadataFiles:
    """Path metadata file classification."""

    def test_classifies_nerve_morphology(self):
        pm = {
            'data': [
                {
                    'basename': 'SR042-CL1-left_cervical_trunk-NerveMorphology.csv',
                    'dataset_relative_path': (
                        'derivative/sub-SR042/NerveMorphology/'
                        'SR042-VagalTrunks/SR042-left_cervical_trunk/'
                        'SR042-CL1-left_cervical_trunk-NerveMorphology.csv'
                    ),
                    'remote_id': 'package:abc123',
                }
            ],
        }
        result = classify_path_metadata_files(pm)
        assert len(result['nerve_morphology']) == 1
        parsed = result['nerve_morphology'][0]['parsed']
        assert parsed['nerve_name'] == 'left_cervical_trunk'
        assert parsed['sample'] == 'sam-SR042-CL1'
        assert parsed['category'] == 'VagalTrunks'

    def test_classifies_graphml(self):
        pm = {
            'data': [
                {
                    'basename': 'SR042-CL1-left_cervical_trunk-RawFascicleTracking.graphml',
                    'dataset_relative_path': (
                        'derivative/sub-SR042/FascicleMorphology/'
                        'SR042-VagalTrunks/SR042-left_cervical_trunk/'
                        'SR042-CL1-left_cervical_trunk-RawFascicleTracking.graphml'
                    ),
                    'remote_id': 'package:def456',
                }
            ],
        }
        result = classify_path_metadata_files(pm)
        assert len(result['graphml']) == 1

    def test_classifies_summary(self):
        pm = {
            'data': [
                {
                    'basename': 'SR042-left-BranchMorph.csv',
                    'dataset_relative_path': ('derivative/sub-SR042/SummaryMorphology/' 'SR042-left-BranchMorph.csv'),
                    'remote_id': 'package:ghi789',
                }
            ],
        }
        result = classify_path_metadata_files(pm)
        assert len(result['summary']) == 1
        parsed = result['summary'][0]['parsed']
        assert parsed['file_type'] == 'branch_morphology'

    def test_classifies_wrapper(self):
        pm = {
            'data': [
                {
                    'basename': 'SR042-CL1-MicroCTWrapper.json',
                    'dataset_relative_path': ('derivative/sub-SR042/DataWrapper/' 'SR042-CL1-MicroCTWrapper.json'),
                    'remote_id': 'package:jkl012',
                }
            ],
        }
        result = classify_path_metadata_files(pm)
        assert len(result['wrapper']) == 1


# ===================================================================
# Tests: full FK label set validation
# ===================================================================


class TestFKLabelValidity:
    """VAL-EXTRACT-008: All FK labels reference valid lookup entries."""

    def test_all_desc_inst_labels_are_known(self):
        """All desc_inst labels from all functions are from known set."""
        known_desc_inst = {
            'human',
            'tissue',
            'nerve',
            'nerve-cross-section',
            'fascicle-cross-section',
            'sample',
        }

        # Entity extraction
        entities = extract_microct_entities(
            SAMPLE_CURATION_EXPORT,
            MICROCT_UUID,
        )
        for vi in entities['values_inst']:
            assert vi['desc_inst'] in known_desc_inst, f"Unknown desc_inst: {vi['desc_inst']}"

        # Nerve morphology
        nerve_vqs = parse_nerve_morphology(
            SAMPLE_NERVE_CSV,
            'obj1',
            MICROCT_UUID,
            'nerve-test',
        )
        for vq in nerve_vqs:
            assert vq['desc_inst'] in known_desc_inst

        # GraphML
        graphml_result = parse_fascicle_graphml(
            SAMPLE_GRAPHML,
            'obj2',
            MICROCT_UUID,
            'nerve-test',
        )
        for vi in graphml_result['values_inst']:
            assert vi['desc_inst'] in known_desc_inst
        for vq in graphml_result['values_quant']:
            assert vq['desc_inst'] in known_desc_inst
        for vc in graphml_result['values_cat']:
            assert vc['desc_inst'] in known_desc_inst

    def test_all_desc_quant_labels_match_schema(self):
        """All desc_quant labels are from the schema."""
        all_desc_quant = EXPECTED_NERVE_DESC_QUANT | EXPECTED_FASCICLE_DESC_QUANT | EXPECTED_SUMMARY_DESC_QUANT

        nerve_vqs = parse_nerve_morphology(
            SAMPLE_NERVE_CSV,
            'obj1',
            MICROCT_UUID,
            'nerve-test',
        )
        for vq in nerve_vqs:
            assert vq['desc_quant'] in all_desc_quant

        graphml_result = parse_fascicle_graphml(
            SAMPLE_GRAPHML,
            'obj2',
            MICROCT_UUID,
            'nerve-test',
        )
        for vq in graphml_result['values_quant']:
            assert vq['desc_quant'] in all_desc_quant

        summary_result = parse_summary_morphology(
            SAMPLE_BRANCH_CSV,
            'obj3',
            MICROCT_UUID,
        )
        for vq in summary_result['values_quant']:
            assert vq['desc_quant'] in all_desc_quant

    def test_all_desc_cat_labels_match_schema(self):
        graphml_result = parse_fascicle_graphml(
            SAMPLE_GRAPHML,
            'obj2',
            MICROCT_UUID,
            'nerve-test',
        )
        for vc in graphml_result['values_cat']:
            assert vc['desc_cat'] in EXPECTED_EDGE_DESC_CAT

    def test_controlled_term_values_are_known(self):
        graphml_result = parse_fascicle_graphml(
            SAMPLE_GRAPHML,
            'obj2',
            MICROCT_UUID,
            'nerve-test',
        )
        for vc in graphml_result['values_cat']:
            assert vc['value_controlled'] in ('true', 'false')


# ===================================================================
# Integration test with live cassava data
# ===================================================================


class TestLiveCassavaIntegration:
    """Integration tests using real cassava API data."""

    @pytest.fixture(scope='class')
    def cassava_data(self):
        return fetch_cassava_metadata(MICROCT_UUID)

    def test_entity_counts(self, cassava_data):
        ce, pm = cassava_data
        result = extract_microct_entities(ce, MICROCT_UUID)
        subjects = [v for v in result['values_inst'] if v['type'] == 'subject']
        samples = [v for v in result['values_inst'] if v['type'] == 'sample']
        assert len(subjects) == 1
        assert len(samples) == 13
        assert len(result['instance_parent']) == 13

    def test_object_extraction(self, cassava_data):
        ce, pm = cassava_data
        result = extract_microct_objects(pm)
        objs = result['objects']
        assert len(objs) > 0
        for obj in objs:
            assert 'uuid' in obj
            assert 'id_type' in obj

    def test_file_classification(self, cassava_data):
        ce, pm = cassava_data
        classified = classify_path_metadata_files(pm)
        assert len(classified['nerve_morphology']) == 56
        assert len(classified['graphml']) == 56
        assert len(classified['wrapper']) > 0
        assert len(classified['summary']) > 0
