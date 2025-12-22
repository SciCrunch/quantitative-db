#!/usr/bin/env python3
"""
DEPRECATED: This file is deprecated. Use ingestion/f006_ingest.py instead.

F006 Dataset Ingestion aligned with quantdb/ingest.py logic

This script implements F006 ingestion using the same logic as quantdb/ingest.py
but with ORM models and YAML-based configuration.

Dataset ID: 2a3d01c0-39d3-464a-8746-54c9d67ebe0f

NOTE: The new f006_ingest.py uses automap_base for dynamic model reflection.
"""
import warnings

warnings.warn(
    'ingestion/f006_ingestion_aligned.py is deprecated. Use ingestion/f006_ingest.py instead.',
    DeprecationWarning,
    stacklevel=2,
)

import csv
import json
import pathlib
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import yaml
from sqlalchemy.orm import Session

from quantdb.client import get_session
from quantdb.generic_ingest import back_populate_tables, get_or_create
from quantdb.models import (
    Addresses,
    Aspects,
    ControlledTerms,
    DescriptorsCat,
    DescriptorsInst,
    DescriptorsQuant,
    ObjDescCat,
    ObjDescInst,
    ObjDescQuant,
    Objects,
    Units,
    ValuesCat,
    ValuesInst,
    ValuesQuant,
)


class F006Ingestion:
    """F006 dataset ingestion following quantdb/ingest.py patterns."""

    def __init__(self, dataset_uuid: str = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'):
        self.dataset_uuid = dataset_uuid
        self.dataset_id = f'dataset:{dataset_uuid}'

        # Load YAML mappings
        mappings_file = pathlib.Path(__file__).parent / 'f006_interlex_mappings.yaml'
        with open(mappings_file, 'r') as f:
            self.mappings = yaml.safe_load(f)

        # Cache directory for CSV files
        self.cache_dir = pathlib.Path(__file__).parent / 'data' / 'csv_cache' / dataset_uuid
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Store created components
        self.components = {}
        self.instances = {}
        self.parents = []

        # Flag to use local data instead of API
        self.use_local_data = False

    def fetch_metadata(self) -> Tuple[Dict, Dict]:
        """Fetch path metadata and curation export from remote API or use local data."""
        if self.use_local_data:
            # Use local path metadata file if available
            local_path_metadata = pathlib.Path(__file__).parent / 'data' / 'f006_path_metadata.json'
            if local_path_metadata.exists():
                import json

                with open(local_path_metadata, 'r') as f:
                    path_metadata = json.load(f)

                # Add type field to path metadata entries if not present
                if 'data' in path_metadata:
                    for j in path_metadata['data']:
                        if 'type' not in j:
                            j['type'] = 'pathmeta'

                # Create minimal curation export for local use
                curation_export = {
                    'dataset_id': self.dataset_uuid,
                    'name': 'F006 Local Dataset',
                    'sites': [],  # Will be populated if needed
                }

                return curation_export, path_metadata
            else:
                print(f'Warning: Local path metadata not found at {local_path_metadata}')
                # Fall through to remote fetch

        # Fetch from remote API
        # Fetch curation export
        resp_dataset = requests.get(
            f'https://cassava.ucsd.edu/sparc/datasets/{self.dataset_uuid}/LATEST/curation-export.json'
        )
        curation_export = resp_dataset.json()

        # Fetch path metadata
        resp = requests.get(f'https://cassava.ucsd.edu/sparc/datasets/{self.dataset_uuid}/LATEST/path-metadata.json')
        path_metadata = resp.json()

        # Add type field to path metadata entries
        for j in path_metadata['data']:
            j['type'] = 'pathmeta'

        return curation_export, path_metadata

    def parse_path_structure(self, path_parts: List[str], dataset_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Parse path structure following quantdb/ingest.py pps function logic.

        Handles structures like:
        - 6 parts: top/subject/sam_1/segment/modality/file
        - 5 parts: top/subject/sam_1/segment/file
        """
        result = {
            'parents': tuple(),
            'subject': None,
            'sample': None,
            'sample_type': 'nerve-cross-section',
            'site': None,
            'site_type': None,
            'fasc': None,
            'modality': None,
            'raw_anat_index_v2': None,
        }

        if len(path_parts) == 6:
            top, subject, sam_1, segment, modality, file = path_parts
            result['subject'] = subject
            result['sample_type'] = 'nerve-cross-section'

            # Check if segment is actually a site
            if segment.startswith('site-'):
                result['site'] = segment
                if dataset_metadata and 'sites' in dataset_metadata:
                    site_meta = [s for s in dataset_metadata['sites'] if s['site_id'] == segment]
                    if site_meta:
                        result['site_type'] = self._translate_site_type(site_meta[0].get('site_type'))
                        result['sample'] = site_meta[0].get('specimen_id')
                else:
                    result['sample'] = None

            # Check if modality is actually a fascicle
            if modality.startswith('fasc-'):
                result['fasc'] = modality

        elif len(path_parts) == 5:
            top, subject, sam_1, segment, file = path_parts
            result['subject'] = subject

            # Check if segment is a site
            if segment.startswith('site-'):
                result['site'] = segment
                if dataset_metadata and 'sites' in dataset_metadata:
                    site_meta = [s for s in dataset_metadata['sites'] if s['site_id'] == segment]
                    if site_meta:
                        result['site_type'] = self._translate_site_type(site_meta[0].get('site_type'))
                        result['sample'] = site_meta[0].get('specimen_id')
                else:
                    result['sample'] = None

            # Determine modality from file type
            if file.endswith('.jpx') and ('9um' in file or '36um' in file):
                result['modality'] = 'microct'
                result['sample_type'] = 'nerve-volume'
            elif file.endswith('fascicles.csv') or file.endswith('fibers.csv'):
                result['modality'] = 'ihc'
                result['sample_type'] = 'nerve-cross-section'

        return result

    def _translate_site_type(self, site_type: str) -> str:
        """Translate site type to standard format."""
        translations = {
            'extruded plane': 'extruded-plane',
        }
        return translations.get(site_type, site_type)

    def _translate_sample_type(self, sample_type: str) -> str:
        """Translate sample type to standard format."""
        translations = {
            'nerve': 'nerve',
            'segment': 'nerve-volume',
            'subsegment': 'nerve-volume',
            'section': 'nerve-cross-section',
        }
        return translations.get(sample_type, sample_type)

    def create_base_components(self, session: Session):
        """Create base components (aspects, units, descriptors) from YAML mappings."""
        # Create aspects
        for aspect_data in self.mappings.get('aspects', []):
            aspect = get_or_create(
                session,
                Aspects(
                    label=aspect_data['label'], iri=aspect_data['iri'], description=aspect_data.get('description', '')
                ),
            )
            self.components[f"aspect_{aspect_data['label']}"] = aspect

        # Create units
        for unit_data in self.mappings.get('units', []):
            unit = get_or_create(session, Units(label=unit_data['label'], iri=unit_data['iri']))
            self.components[f"unit_{unit_data['label']}"] = unit

        # Add missing standard units if not in YAML
        standard_units = [
            {'label': 'micrometer', 'iri': 'http://uri.interlex.org/tgbugs/uris/readable/unit/micrometer'},
            {'label': 'count', 'iri': 'http://uri.interlex.org/tgbugs/uris/readable/unit/count'},
            {'label': 'dimensionless', 'iri': 'http://uri.interlex.org/tgbugs/uris/readable/unit/dimensionless'},
        ]
        for unit_data in standard_units:
            if f"unit_{unit_data['label']}" not in self.components:
                unit = get_or_create(session, Units(label=unit_data['label'], iri=unit_data['iri']))
                self.components[f"unit_{unit_data['label']}"] = unit

        # Create descriptor instances
        for desc_data in self.mappings.get('descriptors', {}).get('instance_types', []):
            desc_inst = get_or_create(
                session,
                DescriptorsInst(
                    label=desc_data['label'], iri=desc_data['iri'], description=desc_data.get('description', '')
                ),
            )
            self.components[f"desc_inst_{desc_data['label']}"] = desc_inst

        # Create controlled terms
        for term_data in self.mappings.get('controlled_terms', []):
            term = get_or_create(session, ControlledTerms(label=term_data['label'], iri=term_data['iri']))
            self.components[f"term_{term_data['label']}"] = term

        # Create addresses
        for addr_name, addr_data in self.mappings.get('addresses', {}).items():
            address = get_or_create(
                session,
                Addresses(
                    addr_type=addr_data['addr_type'],
                    addr_field=addr_data['addr_field'],
                    value_type=addr_data['value_type'],
                    curator_note=addr_data.get('curator_note', ''),
                ),
            )
            self.components[f'addr_{addr_name}'] = address

    def create_quantitative_descriptors(self, session: Session):
        """Create quantitative descriptors from YAML mappings."""
        for desc_data in self.mappings.get('descriptors', {}).get('quantitative', []):
            # Get related components
            domain_key = f"desc_inst_{desc_data['domain']}"
            aspect_key = f"aspect_{desc_data['aspect']}"
            unit_key = f"unit_{desc_data['unit']}"

            if domain_key not in self.components:
                print(f"Warning: Domain {desc_data['domain']} not found")
                continue
            if aspect_key not in self.components:
                print(f"Warning: Aspect {desc_data['aspect']} not found")
                continue
            if unit_key not in self.components:
                print(f"Warning: Unit {desc_data['unit']} not found")
                continue

            desc_quant = get_or_create(
                session,
                DescriptorsQuant(
                    label=desc_data['label'],
                    domain=self.components[domain_key].id,
                    aspect=self.components[aspect_key].id,
                    unit=self.components[unit_key].id,
                    aggregation_type=desc_data.get('aggregation_type', 'instance'),
                    shape=desc_data.get('shape', 'scalar'),
                    description=desc_data.get('description', ''),
                    curator_note=desc_data.get('curator_note', ''),
                ),
            )
            self.components[f"desc_quant_{desc_data['label']}"] = desc_quant

    def create_dataset_object(self, session: Session) -> Objects:
        """Create or get the dataset object."""
        dataset_obj = get_or_create(session, Objects(id=uuid.UUID(self.dataset_uuid), id_type='dataset'))
        self.components['dataset'] = dataset_obj
        return dataset_obj

    def process_path_metadata(self, session: Session, path_metadata: Dict, curation_export: Dict):
        """Process path metadata to create objects and instances."""
        # Filter CSV files
        csvs = [p for p in path_metadata['data'] if 'mimetype' in p and p['mimetype'] == 'text/csv']

        # Separate fascicle and fiber CSVs
        fascs = [p for p in csvs if p['basename'].endswith('fascicles.csv')]
        fibs = [
            p
            for p in csvs
            if p['basename'].endswith('fibers.csv')
            and not pathlib.Path(p['dataset_relative_path']).parts[-2].startswith('fasc-')
        ]

        # Process each CSV file metadata
        all_csvs = fascs + fibs
        for csv_meta in all_csvs:
            self.process_csv_metadata(session, csv_meta, curation_export)

    def process_csv_metadata(self, session: Session, csv_meta: Dict, dataset_metadata: Dict):
        """Process individual CSV file metadata."""
        # Parse path structure
        path_parts = pathlib.Path(csv_meta['dataset_relative_path']).parts
        parsed = self.parse_path_structure(list(path_parts), dataset_metadata)

        # Create file object
        remote_id = csv_meta.get('remote_id', str(uuid.uuid4()))
        if ':' in remote_id:
            remote_id = remote_id.split(':')[-1]  # Extract UUID from N:package:uuid format

        file_obj = get_or_create(
            session,
            Objects(
                id=uuid.UUID(remote_id) if isinstance(remote_id, str) else remote_id,
                id_type='package',
                id_file=csv_meta.get('file_id'),
            ),
        )

        # Create instances for subject, sample, site, fascicle as needed
        if parsed['subject']:
            self.create_instance_hierarchy(session, parsed, file_obj)

        # Process CSV data if available
        if self.should_process_csv(csv_meta):
            self.process_csv_data(session, csv_meta, parsed, file_obj)

    def create_instance_hierarchy(self, session: Session, parsed: Dict, file_obj: Objects):
        """Create hierarchy of instances (subject -> sample -> site -> fascicle)."""
        dataset = self.components['dataset']

        # Create subject instance
        if parsed['subject']:
            subject_inst = get_or_create(
                session,
                ValuesInst(
                    type='subject',
                    id_sub=parsed['subject'],
                    id_formal=parsed['subject'],
                    dataset=dataset.id,
                    desc_inst=self.components.get('desc_inst_nerve-cross-section', {}).id
                    if 'desc_inst_nerve-cross-section' in self.components
                    else None,
                ),
            )
            self.instances[parsed['subject']] = subject_inst

        # Create sample instance if exists
        if parsed['sample']:
            sample_inst = get_or_create(
                session,
                ValuesInst(
                    type='sample',
                    id_sub=parsed['subject'],
                    id_sam=parsed['sample'],
                    id_formal=parsed['sample'],
                    dataset=dataset.id,
                    desc_inst=self.components.get('desc_inst_nerve-cross-section', {}).id
                    if 'desc_inst_nerve-cross-section' in self.components
                    else None,
                ),
            )
            key = f"{parsed['subject']}_{parsed['sample']}"
            self.instances[key] = sample_inst

            # Record parent relationship
            self.parents.append((dataset.id, parsed['sample'], parsed['subject']))

        # Create site instance if exists
        if parsed['site']:
            parent = parsed['sample'] if parsed['sample'] else parsed['subject']
            site_inst = get_or_create(
                session,
                ValuesInst(
                    type='below',
                    id_sub=parsed['subject'],
                    id_sam=parsed.get('sample'),
                    id_formal=parsed['site'],
                    dataset=dataset.id,
                    desc_inst=self.components.get('desc_inst_nerve-cross-section', {}).id
                    if 'desc_inst_nerve-cross-section' in self.components
                    else None,
                ),
            )
            key = f"{parsed['subject']}_{parsed['site']}"
            self.instances[key] = site_inst

            # Record parent relationship
            self.parents.append((dataset.id, parsed['site'], parent))

        # Create fascicle instance if exists
        if parsed['fasc']:
            parent = parsed['site'] if parsed['site'] else parsed['sample'] if parsed['sample'] else parsed['subject']
            fasc_inst = get_or_create(
                session,
                ValuesInst(
                    type='below',
                    id_sub=parsed['subject'],
                    id_sam=parsed.get('sample'),
                    id_formal=parsed['fasc'],
                    dataset=dataset.id,
                    desc_inst=self.components.get('desc_inst_fascicle-cross-section', {}).id
                    if 'desc_inst_fascicle-cross-section' in self.components
                    else None,
                ),
            )
            key = f"{parsed['subject']}_{parsed['fasc']}"
            self.instances[key] = fasc_inst

            # Record parent relationship
            self.parents.append((dataset.id, parsed['fasc'], parent))

    def should_process_csv(self, csv_meta: Dict) -> bool:
        """Determine if CSV should be processed for data extraction."""
        basename = csv_meta.get('basename', '')
        return basename.endswith('fascicles.csv') or basename.endswith('fibers.csv')

    def process_csv_data(self, session: Session, csv_meta: Dict, parsed: Dict, file_obj: Objects):
        """Process CSV data to extract values."""
        # Download and cache CSV file
        csv_path = self.download_csv(csv_meta)
        if not csv_path or not csv_path.exists():
            print(f"Failed to download CSV: {csv_meta['dataset_relative_path']}")
            return

        # Read CSV data
        try:
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)
                if not rows:
                    return

                header = rows[0]
                data_rows = rows[1:]

        except Exception as e:
            print(f'Error reading CSV {csv_path}: {e}')
            return

        # Process based on file type
        if csv_meta['basename'].endswith('fascicles.csv'):
            self.process_fascicle_csv(session, header, data_rows, parsed, file_obj)
        elif csv_meta['basename'].endswith('fibers.csv'):
            self.process_fiber_csv(session, header, data_rows, parsed, file_obj)

    def download_csv(self, csv_meta: Dict) -> Optional[pathlib.Path]:
        """Download CSV file to cache directory."""
        # Check if already cached
        file_id = csv_meta.get('file_id', csv_meta.get('remote_id', '').split(':')[-1])
        cached_path = self.cache_dir / f"{file_id}_{csv_meta['basename']}"

        if cached_path.exists():
            return cached_path

        # Download from Pennsieve if not cached
        try:
            # This would use the actual Pennsieve API to download
            # For now, check if file exists in expected location
            local_path = pathlib.Path('ingestion/data/csv_cache') / self.dataset_uuid / csv_meta['basename']
            if local_path.exists():
                return local_path
        except Exception as e:
            print(f"Error downloading {csv_meta['basename']}: {e}")

        return None

    def process_fascicle_csv(
        self, session: Session, header: List[str], data_rows: List[List[str]], parsed: Dict, file_obj: Objects
    ):
        """Process fascicle CSV data to create quantitative values."""
        # Column mappings for fascicle data
        column_mappings = {
            'fascicle': 'fascicle_id',
            'area': 'fascicle_area',
            'longest_diameter': 'fascicle_longest_diameter',
            'shortest_diameter': 'fascicle_shortest_diameter',
            'eff_diam': 'fascicle_eff_diam',
            'x_cent': 'fascicle_x_cent',
            'y_cent': 'fascicle_y_cent',
            'n_a_alpha': 'n_a_alpha',
            'n_a_beta': 'n_a_beta',
            'n_a_gamma': 'n_a_gamma',
            'n_a_delta': 'n_a_delta',
            'n_b': 'n_b',
            'n_unmyel_nf': 'n_unmyel_nf',
            'n_nav': 'n_nav',
            'n_chat': 'n_chat',
            'n_myelinated': 'n_myelinated',
            'area_a_alpha': 'area_a_alpha',
            'area_a_beta': 'area_a_beta',
            'area_a_gamma': 'area_a_gamma',
            'area_a_delta': 'area_a_delta',
            'area_b': 'area_b',
            'area_unmyel_nf': 'area_unmyel_nf',
            'area_nav': 'area_nav',
            'area_chat': 'area_chat',
            'area_myelinated': 'area_myelinated',
        }

        # Find column indices
        col_indices = {}
        for col_name, mapping_name in column_mappings.items():
            if col_name in header:
                col_indices[mapping_name] = header.index(col_name)

        # Process each data row
        for row in data_rows:
            if not row or all(not cell for cell in row):
                continue

            # Create fascicle instance
            if 'fascicle_id' in col_indices:
                fasc_id = row[col_indices['fascicle_id']]
                base = parsed['sample'] if parsed['site'] is None else parsed['site']
                fasc_formal = f'fasc-{base}-{fasc_id}'

                fasc_inst = get_or_create(
                    session,
                    ValuesInst(
                        type='below',
                        id_sub=parsed['subject'],
                        id_sam=parsed.get('sample'),
                        id_formal=fasc_formal,
                        dataset=self.components['dataset'].id,
                        desc_inst=self.components.get('desc_inst_fascicle-cross-section', {}).id
                        if 'desc_inst_fascicle-cross-section' in self.components
                        else None,
                    ),
                )

                # Create quantitative values
                self.create_fascicle_values(session, row, col_indices, fasc_inst, file_obj)

    def create_fascicle_values(
        self, session: Session, row: List[str], col_indices: Dict, fasc_inst: ValuesInst, file_obj: Objects
    ):
        """Create quantitative values for fascicle measurements."""
        # Map column names to descriptor labels
        value_mappings = {
            'fascicle_area': 'fascicle cross section area um2',
            'fascicle_eff_diam': 'fascicle cross section diameter um',
            'fascicle_longest_diameter': 'fascicle cross section diameter um max',
            'fascicle_shortest_diameter': 'fascicle cross section diameter um min',
            'fascicle_x_cent': 'fascicle centroid x position um',
            'fascicle_y_cent': 'fascicle centroid y position um',
            'n_a_alpha': 'alpha a fiber count in fascicle cross section',
            'n_a_beta': 'beta a fiber count in fascicle cross section',
            'n_a_gamma': 'gamma a fiber count in fascicle cross section',
            'n_a_delta': 'delta a fiber count in fascicle cross section',
            'n_b': 'b fiber count in fascicle cross section',
            'n_unmyel_nf': 'unmyelinated fiber count in fascicle cross section',
            'n_nav': 'nav fiber count in fascicle cross section',
            'n_chat': 'chat fiber count in fascicle cross section',
            'n_myelinated': 'myelinated fiber count in fascicle cross section',
            'area_a_alpha': 'alpha a fiber area in fascicle cross section um2',
            'area_a_beta': 'beta a fiber area in fascicle cross section um2',
            'area_a_gamma': 'gamma a fiber area in fascicle cross section um2',
            'area_a_delta': 'delta a fiber area in fascicle cross section um2',
            'area_b': 'b fiber area in fascicle cross section um2',
            'area_unmyel_nf': 'unmyelinated fiber area in fascicle cross section um2',
            'area_nav': 'nav fiber area in fascicle cross section um2',
            'area_chat': 'chat fiber area in fascicle cross section um2',
            'area_myelinated': 'myelinated fiber area in fascicle cross section um2',
        }

        for col_name, desc_label in value_mappings.items():
            if col_name in col_indices and f'desc_quant_{desc_label}' in self.components:
                try:
                    value_str = row[col_indices[col_name]]
                    if value_str and value_str.strip():
                        value = float(value_str)
                        desc_quant = self.components[f'desc_quant_{desc_label}']

                        # Create ObjDescQuant if needed
                        addr_key = f'addr_{col_name}'
                        addr_id = self.components[addr_key].id if addr_key in self.components else 1

                        obj_desc_quant = get_or_create(
                            session,
                            ObjDescQuant(object=file_obj.id, desc_quant=desc_quant.id, addr_field=addr_id, expect=1),
                        )

                        # Create value
                        value_quant = get_or_create(
                            session,
                            ValuesQuant(
                                value=value,
                                object=file_obj.id,
                                desc_inst=fasc_inst.desc_inst if fasc_inst.desc_inst else 1,
                                desc_quant=desc_quant.id,
                                instance=fasc_inst.id,
                                value_blob={'raw': value_str},
                                orig_value=value_str,
                            ),
                        )

                except (ValueError, TypeError) as e:
                    pass  # Skip invalid values

    def process_fiber_csv(
        self, session: Session, header: List[str], data_rows: List[List[str]], parsed: Dict, file_obj: Objects
    ):
        """Process fiber CSV data to create quantitative values."""
        # Column mappings for fiber data
        column_mappings = {
            'fiber_area': 'fiber_area',
            'eff_fib_diam': 'fiber_eff_diam',
            'longest_diameter': 'fiber_longest_diameter',
            'shortest_diameter': 'fiber_shortest_diameter',
            'x': 'fiber_x',
            'y': 'fiber_y',
            'rho': 'fiber_rho',
            'phi': 'fiber_phi',
        }

        # Find column indices
        col_indices = {}
        for col_name, mapping_name in column_mappings.items():
            if col_name in header:
                col_indices[mapping_name] = header.index(col_name)

        # Process each data row
        for idx, row in enumerate(data_rows):
            if not row or all(not cell for cell in row):
                continue

            # Create fiber instance
            base = parsed['sample'] if parsed['site'] is None else parsed['site']
            fiber_formal = f'fiber-{base}-{idx+1}'

            fiber_inst = get_or_create(
                session,
                ValuesInst(
                    type='below',
                    id_sub=parsed['subject'],
                    id_sam=parsed.get('sample'),
                    id_formal=fiber_formal,
                    dataset=self.components['dataset'].id,
                    desc_inst=self.components.get('desc_inst_fiber-cross-section', {}).id
                    if 'desc_inst_fiber-cross-section' in self.components
                    else None,
                ),
            )

            # Create fiber values
            self.create_fiber_values(session, row, col_indices, fiber_inst, file_obj)

    def create_fiber_values(
        self, session: Session, row: List[str], col_indices: Dict, fiber_inst: ValuesInst, file_obj: Objects
    ):
        """Create quantitative values for fiber measurements."""
        # Map column names to descriptor labels
        value_mappings = {
            'fiber_area': 'fiber cross section area um2',
            'fiber_eff_diam': 'fiber cross section diameter um',
            'fiber_longest_diameter': 'fiber cross section diameter um max',
            'fiber_shortest_diameter': 'fiber cross section diameter um min',
            'fiber_x': 'fiber centroid x position um',
            'fiber_y': 'fiber centroid y position um',
            'fiber_rho': 'fiber radius from fascicle centroid um',
            'fiber_phi': 'fiber angle from fascicle centroid radians',
        }

        for col_name, desc_label in value_mappings.items():
            if col_name in col_indices and f'desc_quant_{desc_label}' in self.components:
                try:
                    value_str = row[col_indices[col_name]]
                    if value_str and value_str.strip():
                        value = float(value_str)
                        desc_quant = self.components[f'desc_quant_{desc_label}']

                        # Create ObjDescQuant if needed
                        addr_key = f'addr_{col_name}'
                        addr_id = self.components[addr_key].id if addr_key in self.components else 1

                        obj_desc_quant = get_or_create(
                            session,
                            ObjDescQuant(object=file_obj.id, desc_quant=desc_quant.id, addr_field=addr_id, expect=1),
                        )

                        # Create value
                        value_quant = get_or_create(
                            session,
                            ValuesQuant(
                                value=value,
                                object=file_obj.id,
                                desc_inst=fiber_inst.desc_inst if fiber_inst.desc_inst else 1,
                                desc_quant=desc_quant.id,
                                instance=fiber_inst.id,
                                value_blob={'raw': value_str},
                                orig_value=value_str,
                            ),
                        )

                except (ValueError, TypeError) as e:
                    pass  # Skip invalid values

    def run(self, session: Session, commit: bool = False):
        """Run the complete F006 ingestion pipeline."""
        try:
            print(f'Starting F006 ingestion for dataset {self.dataset_uuid}')

            # Fetch metadata
            print('Fetching metadata from remote API...')
            curation_export, path_metadata = self.fetch_metadata()

            # Create base components
            print('Creating base components...')
            self.create_base_components(session)

            # Create quantitative descriptors
            print('Creating quantitative descriptors...')
            self.create_quantitative_descriptors(session)

            # Create dataset object
            print('Creating dataset object...')
            self.create_dataset_object(session)

            # Process path metadata and CSV files
            print('Processing path metadata and CSV files...')
            self.process_path_metadata(session, path_metadata, curation_export)

            if commit:
                session.commit()
                print('Changes committed to database')
            else:
                print('Dry run complete - no changes committed')

            # Report statistics
            print(f'\nIngestion Statistics:')
            print(f'  Components created: {len(self.components)}')
            print(f'  Instances created: {len(self.instances)}')
            print(f'  Parent relationships: {len(self.parents)}')

        except Exception as e:
            print(f'Error during ingestion: {e}')
            session.rollback()
            raise


def main():
    """Main entry point for F006 ingestion."""
    import argparse

    parser = argparse.ArgumentParser(description='F006 Dataset Ingestion')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database')
    parser.add_argument('--test', action='store_true', help='Use test database')
    args = parser.parse_args()

    # Get database session
    session = get_session(test=args.test)

    # Run ingestion
    ingestion = F006Ingestion()
    ingestion.run(session, commit=args.commit)

    # Close session
    session.close()


if __name__ == '__main__':
    main()
