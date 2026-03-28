"""MicroCT data extraction module.

Fetches metadata from cassava and parses all MicroCT data files
(NerveMorphology CSV, RawFascicleTracking GraphML, SummaryMorphology CSV,
DataWrapper JSON) into flat dicts with string FK labels ready for
``Ingest.batch()``.

Dataset: REVA CD MicroCT (fb1cbd05-4320-4d8b-ac3a-44f1fe810718)
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from typing import Any

import networkx as nx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MICROCT_UUID = 'fb1cbd05-4320-4d8b-ac3a-44f1fe810718'

CASSAVA_BASE = (
    'https://cassava.ucsd.edu/sparc/datasets'
    f'/{MICROCT_UUID}/LATEST'
)

# Pixel conversion factors (from MicroCTDataStandard.md)
PIXEL_TO_UM = 11.4
PIXEL_TO_UM2 = 129.96  # 11.4 * 11.4

# Nerve morphology CSV column → descriptor_quant label mapping
# These columns are in pixel units and need conversion
_NERVE_MORPH_COLUMNS = {
    'area': 'nerve cross section area pixel-11um',
    'perimeter': 'nerve cross section perimeter pixel-11um',
    'eq_diameter': 'nerve cross section eq diameter pixel-11um',
    'center_x': 'nerve cross section centroid-x pixel-11um',
    'center_y': 'nerve cross section centroid-y pixel-11um',
    'major_axis': 'nerve cross section major axis pixel-11um',
    'minor_axis': 'nerve cross section minor axis pixel-11um',
    'angle': 'nerve cross section angle degree',
}

# GraphML fascicle node property → descriptor_quant label mapping
_FASCICLE_NODE_COLUMNS = {
    'area': 'fascicle cross section area pixel-11um',
    'equivalent_diameter': 'fascicle cross section eq diameter pixel-11um',
    'centroid-0': 'fascicle cross section centroid-0 pixel-11um',
    'centroid-1': 'fascicle cross section centroid-1 pixel-11um',
    'ellipse_major_axis': 'fascicle cross section major axis pixel-11um',
    'ellipse_minor_axis': 'fascicle cross section minor axis pixel-11um',
    'ellipse_angle': 'fascicle cross section angle degree',
}

# GraphML edge boolean property → descriptor_cat label mapping
_EDGE_BOOL_COLUMNS = {
    'identity': 'fascicleEdgeIdentity',
    'split': 'fascicleEdgeSplit',
    'merge': 'fascicleEdgeMerge',
}

# Summary morphology CSV column → descriptor_quant label mapping
# (BranchMorphology.csv and CranialNervesMorphology.csv)
_SUMMARY_MORPH_COLUMNS = {
    'median_nerve_diam_mm': 'median nerve diameter mm',
    'sd_nerve_diam_mm': 'sd nerve diameter mm',
    'median_nerve_area_mm2': 'median nerve area mm2',
    'sd_nerve_area_mm2': 'sd nerve area mm2',
    'endo_area_mm2': 'endoneurial area mm2',
    'num_fas': 'fascicle count',
    'avg_fas_diam_mm': 'avg fascicle diameter mm',
    'sd_fas_diam_mm': 'sd fascicle diameter mm',
    'min_fas_diam_mm': 'min fascicle diameter mm',
    'max_fas_diam_mm': 'max fascicle diameter mm',
    'measurement_dist_mm': 'measurement distance mm',
    'measurement_frame': 'measurement frame',
}

# Trunk NerveMorph and FasMorph columns (per-slice pixel-unit data)
_TRUNK_NERVE_MORPH_COLUMNS = {
    'area': 'nerve cross section area pixel-11um',
    'perimeter': 'nerve cross section perimeter pixel-11um',
    'eq_diameter': 'nerve cross section eq diameter pixel-11um',
    'center_x': 'nerve cross section centroid-x pixel-11um',
    'center_y': 'nerve cross section centroid-y pixel-11um',
    'major_axis': 'nerve cross section major axis pixel-11um',
    'minor_axis': 'nerve cross section minor axis pixel-11um',
    'angle': 'nerve cross section angle degree',
}

_TRUNK_FAS_MORPH_COLUMNS = {
    'area': 'fascicle cross section area pixel-11um',
    'equivalent_diameter': 'fascicle cross section eq diameter pixel-11um',
    'centroid-0': 'fascicle cross section centroid-0 pixel-11um',
    'centroid-1': 'fascicle cross section centroid-1 pixel-11um',
    'ellipse_major_axis': 'fascicle cross section major axis pixel-11um',
    'ellipse_minor_axis': 'fascicle cross section minor axis pixel-11um',
    'ellipse_angle': 'fascicle cross section angle degree',
}


# ---------------------------------------------------------------------------
# Cassava metadata fetch
# ---------------------------------------------------------------------------


def fetch_cassava_metadata(
    dataset_uuid: str = MICROCT_UUID,
) -> tuple[dict, dict]:
    """Fetch curation-export.json and path-metadata.json from cassava.

    Parameters
    ----------
    dataset_uuid : str
        The dataset UUID string.

    Returns
    -------
    tuple[dict, dict]
        (curation_export, path_metadata) parsed JSON dicts.
    """
    base = (
        f'https://cassava.ucsd.edu/sparc/datasets'
        f'/{dataset_uuid}/LATEST'
    )

    ce_url = f'{base}/curation-export.json'
    pm_url = f'{base}/path-metadata.json'

    with urllib.request.urlopen(ce_url) as resp:
        curation_export = json.loads(resp.read())

    with urllib.request.urlopen(pm_url) as resp:
        path_metadata = json.loads(resp.read())

    return curation_export, path_metadata


# ---------------------------------------------------------------------------
# Entity extraction (subjects, samples, hierarchy)
# ---------------------------------------------------------------------------


def extract_microct_entities(
    curation_export: dict,
    dataset_uuid: str = MICROCT_UUID,
) -> dict[str, list]:
    """Extract subjects, samples, and parent-child relationships.

    Follows the ``extract_entities_v2()`` pattern from ``extract_v2.py``.
    MicroCT dataset has 1 subject (sub-SR042) and 13 samples
    (sam-SR042-CL1, etc.). Sample type is 'Tissue' which maps to
    desc_inst 'tissue'. No sites.

    Parameters
    ----------
    curation_export : dict
        Parsed curation-export.json for the dataset.
    dataset_uuid : str
        The dataset UUID string.

    Returns
    -------
    dict
        Keys ``'values_inst'`` and ``'instance_parent'``.
        ``values_inst`` is a list of flat dicts for subjects and samples.
        ``instance_parent`` is a list of ``{'child': id, 'parent': id}``
        dicts.
    """
    values_inst = []
    instance_parent = []

    # --- Subjects ---
    for ent in curation_export.get('subjects', []):
        subject_id = ent['subject_id']
        species = ent.get('species')

        # Translate species
        desc_inst = None
        if species:
            if isinstance(species, dict):
                species_val = species.get('id', '')
            else:
                species_val = species
            species_lower = str(species_val).lower()
            if 'ncbitaxon_9606' in species_lower or 'ncbitaxon:9606' in species_lower:
                desc_inst = 'human'

        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': subject_id,
            'type': 'subject',
            'desc_inst': desc_inst,
            'id_sub': subject_id,
        })

    # --- Samples ---
    for ent in curation_export.get('samples', []):
        sample_id = ent['sample_id']
        subject_id = ent['subject_id']

        # Map sample type: MicroCT uses 'Tissue'
        sample_type = ent.get('sample_type', '')
        if sample_type.lower() == 'tissue':
            desc_inst = 'tissue'
        elif sample_type.lower() == 'nerve':
            desc_inst = 'nerve'
        elif sample_type.lower() == 'segment':
            desc_inst = 'nerve-volume'
        else:
            desc_inst = 'sample'

        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': sample_id,
            'type': 'sample',
            'desc_inst': desc_inst,
            'id_sub': subject_id,
            'id_sam': sample_id,
        })

        # Parent relationship: sample → subject
        wdf = ent.get('was_derived_from')
        if wdf:
            if isinstance(wdf, list):
                for p in wdf:
                    instance_parent.append({
                        'child': sample_id,
                        'parent': p,
                    })
            else:
                instance_parent.append({
                    'child': sample_id,
                    'parent': wdf,
                })
        else:
            instance_parent.append({
                'child': sample_id,
                'parent': subject_id,
            })

    return {
        'values_inst': values_inst,
        'instance_parent': instance_parent,
    }


# ---------------------------------------------------------------------------
# NerveMorphology CSV parsing
# ---------------------------------------------------------------------------


def _is_blank_row(row: dict, columns: list[str]) -> bool:
    """Check if a CSV row is blank (all measurement columns empty).

    The MicroCT spec says: a blank row (except for index) indicates
    measurement is not available.
    """
    for col in columns:
        val = row.get(col, '').strip()
        if val:
            return False
    return True


def parse_nerve_morphology(
    csv_content: str,
    object_uuid: str,
    dataset_uuid: str,
    nerve_id_formal: str,
) -> list[dict[str, Any]]:
    """Parse NerveMorphology.csv content into flat value dicts.

    Values are stored in pixel-11um units (the raw pixel values as-is),
    matching the descriptor labels in inserts_microct.sql.
    Angle values are in degrees and stored unchanged.
    Blank rows (where the nerve intersects with other neural structures)
    are skipped.

    Parameters
    ----------
    csv_content : str
        Raw CSV string content.
    object_uuid : str
        UUID of the file object (from path-metadata remote_id).
    dataset_uuid : str
        The dataset UUID string.
    nerve_id_formal : str
        The id_formal of the nerve instance (e.g.,
        'nerve-SR042-CL1-left_cervical_trunk').

    Returns
    -------
    list[dict]
        List of values_quant flat dicts.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    measurement_cols = [
        'area', 'perimeter', 'eq_diameter', 'center_x',
        'center_y', 'major_axis', 'minor_axis', 'angle',
    ]
    values_quant = []

    for row in reader:
        # Skip blank rows
        if _is_blank_row(row, measurement_cols):
            continue

        index_val = row.get('index', '').strip()
        slice_id_formal = f'{nerve_id_formal}-slice-{index_val}'

        for csv_col, desc_quant in _NERVE_MORPH_COLUMNS.items():
            raw = row.get(csv_col, '').strip()
            if not raw:
                continue

            value = float(raw)

            values_quant.append({
                'value': value,
                'value_blob': value,
                'object': object_uuid,
                'desc_inst': 'nerve-cross-section',
                'desc_quant': desc_quant,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': slice_id_formal,
                },
            })

    return values_quant


# ---------------------------------------------------------------------------
# GraphML (RawFascicleTracking) parsing
# ---------------------------------------------------------------------------


def parse_fascicle_graphml(
    graphml_content: str,
    object_uuid: str,
    dataset_uuid: str,
    nerve_id_formal: str,
) -> dict[str, list]:
    """Parse RawFascicleTracking GraphML into flat dicts.

    Each graph node represents a fascicle with measurements.
    Each graph edge has boolean properties (identity, split, merge).

    Node measurements are stored in pixel-11um units (raw values).
    Angle values are in degrees and stored unchanged.

    Parameters
    ----------
    graphml_content : str
        Raw GraphML XML string content.
    object_uuid : str
        UUID of the file object.
    dataset_uuid : str
        The dataset UUID string.
    nerve_id_formal : str
        The id_formal of the parent nerve instance.

    Returns
    -------
    dict
        Keys: ``'values_inst'``, ``'instance_parent'``,
        ``'values_quant'``, ``'values_cat'``.
    """
    G = nx.read_graphml(io.BytesIO(graphml_content.encode('utf-8')))

    values_inst = []
    instance_parent = []
    values_quant = []
    values_cat = []

    # --- Process nodes ---
    for node_id, node_data in G.nodes(data=True):
        frame = node_data.get('frame', '')
        # Create a unique fascicle instance id_formal
        fasc_id_formal = (
            f'{nerve_id_formal}-frame-{frame}-fasc-{node_id}'
        )

        # Create slice instance (nerve cross-section for this frame)
        slice_id_formal = f'{nerve_id_formal}-slice-{frame}'

        # Fascicle instance
        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': fasc_id_formal,
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
        })

        # Parent: fascicle → slice
        instance_parent.append({
            'child': fasc_id_formal,
            'parent': slice_id_formal,
        })

        # Quantitative measurements for each fascicle node
        for prop_name, desc_quant in _FASCICLE_NODE_COLUMNS.items():
            raw = node_data.get(prop_name)
            if raw is None:
                continue

            value = float(raw)

            values_quant.append({
                'value': value,
                'value_blob': value,
                'object': object_uuid,
                'desc_inst': 'fascicle-cross-section',
                'desc_quant': desc_quant,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': fasc_id_formal,
                },
            })

    # --- Process edges ---
    for source, target, edge_data in G.edges(data=True):
        # Get the source node's frame and id_formal
        source_data = G.nodes[source]
        source_frame = source_data.get('frame', '')
        source_id_formal = (
            f'{nerve_id_formal}-frame-{source_frame}-fasc-{source}'
        )

        for prop_name, desc_cat in _EDGE_BOOL_COLUMNS.items():
            raw = edge_data.get(prop_name)
            if raw is None:
                continue

            # Convert to string 'true'/'false' matching controlled_terms
            if isinstance(raw, bool):
                value = 'true' if raw else 'false'
            elif isinstance(raw, str):
                value = raw.lower()
            else:
                value = str(raw).lower()

            values_cat.append({
                'value_controlled': value,
                'object': object_uuid,
                'desc_inst': 'fascicle-cross-section',
                'desc_cat': desc_cat,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': source_id_formal,
                },
            })

    return {
        'values_inst': values_inst,
        'instance_parent': instance_parent,
        'values_quant': values_quant,
        'values_cat': values_cat,
    }


# ---------------------------------------------------------------------------
# Summary morphology CSV parsing
# (BranchMorphology.csv and CranialNervesMorphology.csv)
# ---------------------------------------------------------------------------


def parse_summary_morphology(
    csv_content: str,
    object_uuid: str,
    dataset_uuid: str,
) -> dict[str, list]:
    """Parse BranchMorphology or CranialNervesMorphology CSV.

    Values are already in mm/mm2, stored as-is.
    Each row produces an instance (nerve structure) and quantitative
    value dicts.

    Parameters
    ----------
    csv_content : str
        Raw CSV string content.
    object_uuid : str
        UUID of the file object.
    dataset_uuid : str
        The dataset UUID string.

    Returns
    -------
    dict
        Keys: ``'values_inst'``, ``'instance_parent'``,
        ``'values_quant'``.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    values_inst = []
    instance_parent = []
    values_quant = []

    for row in reader:
        # Determine nerve/branch name for id_formal
        subject = row.get('subject', '').strip()
        sample = row.get('sample', '').strip()
        branch_name = row.get('branch_name', '').strip()
        nerve_name = row.get('nerve_name', '').strip()

        name = branch_name or nerve_name
        if not name:
            continue

        # Build id_formal for this summary entry
        id_formal = f'summary-{subject}-{sample}-{name}'

        # Parent is the sample
        sample_id_formal = f'sam-{subject}-{sample}'

        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': id_formal,
            'type': 'below',
            'desc_inst': 'nerve',
        })

        instance_parent.append({
            'child': id_formal,
            'parent': sample_id_formal,
        })

        for csv_col, desc_quant in _SUMMARY_MORPH_COLUMNS.items():
            raw = row.get(csv_col, '').strip()
            if not raw:
                continue

            try:
                value = float(raw)
            except ValueError:
                continue

            values_quant.append({
                'value': value,
                'value_blob': value,
                'object': object_uuid,
                'desc_inst': 'nerve',
                'desc_quant': desc_quant,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': id_formal,
                },
            })

    return {
        'values_inst': values_inst,
        'instance_parent': instance_parent,
        'values_quant': values_quant,
    }


# ---------------------------------------------------------------------------
# Trunk NerveMorph / FasMorph CSV parsing (per-slice, pixel units)
# ---------------------------------------------------------------------------


def parse_trunk_nerve_morphology(
    csv_content: str,
    object_uuid: str,
    dataset_uuid: str,
    trunk_id_formal: str,
) -> dict[str, list]:
    """Parse trunk NerveMorph.csv (per-slice, pixel units + dist_global).

    These are the SummaryMorphology/<SUBJECT>-<TRUNK>-NerveMorph.csv
    files that contain per-slice data for trunk nerves, with additional
    columns 'segment' and 'dist_global'.

    Parameters
    ----------
    csv_content : str
        Raw CSV string content.
    object_uuid : str
        UUID of the file object.
    dataset_uuid : str
        The dataset UUID string.
    trunk_id_formal : str
        The id_formal of the trunk nerve instance
        (e.g., 'trunk-SR042-left_cervical_trunk').

    Returns
    -------
    dict
        Keys: ``'values_inst'``, ``'instance_parent'``,
        ``'values_quant'``.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    measurement_cols = list(_TRUNK_NERVE_MORPH_COLUMNS.keys())
    values_inst = []
    instance_parent = []
    values_quant = []

    for row in reader:
        if _is_blank_row(row, measurement_cols):
            continue

        index_val = row.get('index', '').strip()
        slice_id_formal = f'{trunk_id_formal}-slice-{index_val}'

        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': slice_id_formal,
            'type': 'below',
            'desc_inst': 'nerve-cross-section',
        })
        instance_parent.append({
            'child': slice_id_formal,
            'parent': trunk_id_formal,
        })

        # Per-slice nerve measurements
        for csv_col, desc_quant in _TRUNK_NERVE_MORPH_COLUMNS.items():
            raw = row.get(csv_col, '').strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            values_quant.append({
                'value': value,
                'value_blob': value,
                'object': object_uuid,
                'desc_inst': 'nerve-cross-section',
                'desc_quant': desc_quant,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': slice_id_formal,
                },
            })

        # dist_global column (in mm)
        dist_raw = row.get('dist_global', '').strip()
        if dist_raw:
            try:
                dist_val = float(dist_raw)
                values_quant.append({
                    'value': dist_val,
                    'value_blob': dist_val,
                    'object': object_uuid,
                    'desc_inst': 'nerve-cross-section',
                    'desc_quant': 'global distance mm',
                    'instance': {
                        'dataset': dataset_uuid,
                        'id_formal': slice_id_formal,
                    },
                })
            except ValueError:
                pass

    return {
        'values_inst': values_inst,
        'instance_parent': instance_parent,
        'values_quant': values_quant,
    }


def parse_trunk_fas_morphology(
    csv_content: str,
    object_uuid: str,
    dataset_uuid: str,
    trunk_id_formal: str,
) -> dict[str, list]:
    """Parse trunk FasMorph.csv (per-slice fascicle, pixel units).

    These are the SummaryMorphology/<SUBJECT>-<TRUNK>-FasMorph.csv
    files with per-slice fascicle measurements.

    Parameters
    ----------
    csv_content : str
        Raw CSV string content.
    object_uuid : str
        UUID of the file object.
    dataset_uuid : str
        The dataset UUID string.
    trunk_id_formal : str
        The id_formal of the trunk nerve instance.

    Returns
    -------
    dict
        Keys: ``'values_inst'``, ``'instance_parent'``,
        ``'values_quant'``.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    measurement_cols = list(_TRUNK_FAS_MORPH_COLUMNS.keys())
    values_inst = []
    instance_parent = []
    values_quant = []
    row_idx = 0

    for row in reader:
        if _is_blank_row(row, measurement_cols):
            continue

        index_val = row.get('index', '').strip()
        slice_id_formal = f'{trunk_id_formal}-slice-{index_val}'

        # Each fascicle row has an implicit index within its slice
        fasc_id_formal = (
            f'{slice_id_formal}-fasc-{row_idx}'
        )
        row_idx += 1

        values_inst.append({
            'dataset': dataset_uuid,
            'id_formal': fasc_id_formal,
            'type': 'below',
            'desc_inst': 'fascicle-cross-section',
        })
        instance_parent.append({
            'child': fasc_id_formal,
            'parent': slice_id_formal,
        })

        for csv_col, desc_quant in _TRUNK_FAS_MORPH_COLUMNS.items():
            raw = row.get(csv_col, '').strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            values_quant.append({
                'value': value,
                'value_blob': value,
                'object': object_uuid,
                'desc_inst': 'fascicle-cross-section',
                'desc_quant': desc_quant,
                'instance': {
                    'dataset': dataset_uuid,
                    'id_formal': fasc_id_formal,
                },
            })

        # dist_global column (in mm)
        dist_raw = row.get('dist_global', '').strip()
        if dist_raw:
            try:
                dist_val = float(dist_raw)
                values_quant.append({
                    'value': dist_val,
                    'value_blob': dist_val,
                    'object': object_uuid,
                    'desc_inst': 'fascicle-cross-section',
                    'desc_quant': 'global distance mm',
                    'instance': {
                        'dataset': dataset_uuid,
                        'id_formal': fasc_id_formal,
                    },
                })
            except ValueError:
                pass

    return {
        'values_inst': values_inst,
        'instance_parent': instance_parent,
        'values_quant': values_quant,
    }


# ---------------------------------------------------------------------------
# DataWrapper JSON parsing
# ---------------------------------------------------------------------------


def parse_data_wrapper(
    json_content: str,
    object_uuid: str,
) -> dict[str, Any]:
    """Parse DataWrapper JSON for imaging metadata.

    Parameters
    ----------
    json_content : str
        Raw JSON string content.
    object_uuid : str
        UUID of the file object.

    Returns
    -------
    dict
        Parsed DataWrapper metadata including pixel properties
        and annotations. Keys: ``'subject_id'``, ``'sample_id'``,
        ``'pixel_properties'``, ``'object_uuid'``.
    """
    data = json.loads(json_content)

    desc = data.get('description', {})
    pixel = data.get('pixel_properties', {})

    return {
        'subject_id': desc.get('subject_id'),
        'sample_id': desc.get('sample_id'),
        'modality': desc.get('modality'),
        'pixel_properties': {
            'dim': pixel.get('dim'),
            'size_x': pixel.get('size_x'),
            'size_y': pixel.get('size_y'),
            'size_z': pixel.get('size_z'),
            'physical_size_x': pixel.get('physical_size_x'),
            'physical_size_y': pixel.get('physical_size_y'),
            'physical_size_z': pixel.get('physical_size_z'),
        },
        'object_uuid': object_uuid,
    }


# ---------------------------------------------------------------------------
# Object extraction from path-metadata
# ---------------------------------------------------------------------------


def _extract_uuid(remote_id: str) -> str:
    """Extract bare UUID string from a remote_id like 'package:UUID'."""
    s = str(remote_id)
    if ':' in s:
        return s.rsplit(':', 1)[-1]
    return s


def _extract_file_id(entry: dict) -> int | None:
    """Extract integer file_id from a path-metadata entry."""
    fid = entry.get('file_id')
    if fid is not None:
        return int(fid)
    uri = entry.get('uri_api', '')
    if uri:
        try:
            return int(uri.rsplit('/', 1)[-1])
        except (ValueError, IndexError):
            return None
    return None


def extract_microct_objects(
    path_metadata: dict,
    dataset_uuid: str = MICROCT_UUID,
) -> dict[str, list]:
    """Extract file objects from path-metadata.json.

    Follows the ``extract_reva_ft_v2()`` pattern from ``extract_v2.py``.

    Parameters
    ----------
    path_metadata : dict
        Parsed path-metadata.json with a ``'data'`` list.
    dataset_uuid : str
        The dataset UUID string.

    Returns
    -------
    dict
        Key ``'objects'``: list of dicts, each with ``'uuid'``,
        ``'file_id'``, ``'id_type'``.
    """
    objects = []
    seen_uuids = set()

    for entry in path_metadata.get('data', []):
        remote_id = entry.get('remote_id', '')
        if not remote_id.startswith('package:'):
            continue

        uuid = _extract_uuid(remote_id)
        if uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)

        file_id = _extract_file_id(entry)

        objects.append({
            'uuid': uuid,
            'file_id': file_id,
            'id_type': 'package',
        })

    return {'objects': objects}


# ---------------------------------------------------------------------------
# Path parsing helpers
# ---------------------------------------------------------------------------


def _parse_nerve_path(drp: str) -> dict | None:
    """Parse a NerveMorphology or GraphML file's path.

    Expected path patterns:
    derivative/sub-SR042/NerveMorphology/SR042-VagalTrunks/
        SR042-<trunk_name>/SR042-<sam>-<trunk_name>-NerveMorphology.csv
    derivative/sub-SR042/FascicleMorphology/SR042-VagalBranches/
        SR042-<branch>/SR042-<sam>-<branch>-RawFascicleTracking.graphml

    Returns dict with 'subject', 'sample', 'nerve_name', 'category'.
    """
    parts = drp.split('/')

    # Find the basename and parse it
    basename = parts[-1] if parts else ''

    # Extract subject from path
    subject = None
    for p in parts:
        if p.startswith('sub-'):
            subject = p
            break

    # Determine category from directory
    category = None
    for p in parts:
        if 'VagalTrunks' in p:
            category = 'VagalTrunks'
            break
        elif 'VagalBranches' in p:
            category = 'VagalBranches'
            break
        elif 'NonVagalCranialNerves' in p:
            category = 'NonVagalCranialNerves'
            break

    if not category or not subject:
        return None

    # Parse basename: SR042-CL1-left_cervical_trunk-NerveMorphology.csv
    # or SR042-CL1-left_cervical_trunk-RawFascicleTracking.graphml
    subject_id = subject.replace('sub-', '')  # e.g., 'SR042'

    # Remove extension
    name_no_ext = basename
    for suffix in [
        '-NerveMorphology.csv',
        '-RawFascicleTracking.graphml',
    ]:
        if name_no_ext.endswith(suffix):
            name_no_ext = name_no_ext[:-len(suffix)]
            break

    # Split: SR042-CL1-left_cervical_trunk
    # The subject_id prefix is first, then sample, then nerve name
    if not name_no_ext.startswith(subject_id + '-'):
        return None

    remainder = name_no_ext[len(subject_id) + 1:]
    # Sample ID is the first component (e.g. 'CL1')
    # Nerve name is the rest (e.g. 'left_cervical_trunk')
    dash_pos = remainder.find('-')
    if dash_pos < 0:
        return None

    sample_code = remainder[:dash_pos]
    nerve_name = remainder[dash_pos + 1:]

    sample_id = f'sam-{subject_id}-{sample_code}'

    return {
        'subject': subject,
        'subject_id': subject_id,
        'sample': sample_id,
        'sample_code': sample_code,
        'nerve_name': nerve_name,
        'category': category,
    }


def _parse_summary_path(drp: str) -> dict | None:
    """Parse a SummaryMorphology file's path.

    Expected patterns:
    derivative/sub-SR042/SummaryMorphology/SR042-left-BranchMorph.csv
    derivative/sub-SR042/SummaryMorphology/SR042-CranialNervesMorph.csv
    derivative/sub-SR042/SummaryMorphology/SR042-left_cervical_trunk-NerveMorph.csv
    derivative/sub-SR042/SummaryMorphology/SR042-left_cervical_trunk-FasMorph.csv

    Returns dict with file type info.
    """
    parts = drp.split('/')
    basename = parts[-1] if parts else ''

    subject = None
    for p in parts:
        if p.startswith('sub-'):
            subject = p
            break

    if not subject:
        return None

    subject_id = subject.replace('sub-', '')

    result = {
        'subject': subject,
        'subject_id': subject_id,
        'basename': basename,
    }

    if basename.endswith('-BranchMorph.csv'):
        result['file_type'] = 'branch_morphology'
    elif basename.endswith('-CranialNervesMorph.csv'):
        result['file_type'] = 'cranial_nerves_morphology'
    elif basename.endswith('-NerveMorph.csv'):
        result['file_type'] = 'trunk_nerve_morphology'
        # Extract trunk name
        name_no_ext = basename.replace('-NerveMorph.csv', '')
        trunk_name = name_no_ext[len(subject_id) + 1:]
        result['trunk_name'] = trunk_name
    elif basename.endswith('-FasMorph.csv'):
        result['file_type'] = 'trunk_fas_morphology'
        name_no_ext = basename.replace('-FasMorph.csv', '')
        trunk_name = name_no_ext[len(subject_id) + 1:]
        result['trunk_name'] = trunk_name
    else:
        return None

    return result


# ---------------------------------------------------------------------------
# High-level extraction orchestrator
# ---------------------------------------------------------------------------


def classify_path_metadata_files(
    path_metadata: dict,
) -> dict[str, list[dict]]:
    """Classify path-metadata entries by file type.

    Returns
    -------
    dict
        Keys: 'nerve_morphology', 'graphml', 'summary', 'wrapper'.
        Each is a list of dicts with 'entry' (the path-metadata entry)
        and 'parsed' (the parsed path info).
    """
    result: dict[str, list[dict]] = {
        'nerve_morphology': [],
        'graphml': [],
        'summary': [],
        'wrapper': [],
    }

    for entry in path_metadata.get('data', []):
        basename = entry.get('basename', '')
        drp = entry.get('dataset_relative_path', '')

        if basename.endswith('-NerveMorphology.csv'):
            parsed = _parse_nerve_path(drp)
            if parsed:
                result['nerve_morphology'].append({
                    'entry': entry,
                    'parsed': parsed,
                })

        elif basename.endswith('-RawFascicleTracking.graphml'):
            parsed = _parse_nerve_path(drp)
            if parsed:
                result['graphml'].append({
                    'entry': entry,
                    'parsed': parsed,
                })

        elif 'SummaryMorphology' in drp and basename.endswith('.csv'):
            parsed = _parse_summary_path(drp)
            if parsed:
                result['summary'].append({
                    'entry': entry,
                    'parsed': parsed,
                })

        elif basename.endswith('-MicroCTWrapper.json'):
            result['wrapper'].append({
                'entry': entry,
            })

    return result
