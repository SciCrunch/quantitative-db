#!/usr/bin/env python3
"""
DEPRECATED: This file is deprecated. Use ingestion/f006_ingest.py instead.

F006 Dataset Ingestion using Generic Study Template

This script implements F006-specific logic using the generic ingestion framework.
Dataset ID: 2a3d01c0-39d3-464a-8746-54c9d67ebe0f

NOTE: This implementation uses hardcoded ORM models from quantdb/models.py.
The new f006_ingest.py uses automap_base for dynamic model reflection.
"""
import warnings

warnings.warn(
    'ingestion/f006.py is deprecated. Use ingestion/f006_ingest.py instead.', DeprecationWarning, stacklevel=2
)

import csv
import pathlib
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from quantdb.generic_ingest import get_or_create
from quantdb.models import (
    Addresses,
    DescriptorsCat,
    DescriptorsInst,
    ObjDescCat,
    ObjDescInst,
    ObjDescQuant,
    ValuesCat,
    ValuesInst,
    ValuesQuant,
)

from .generic_study_template import GenericStudyIngestion
from .utils import (
    download_csv_from_pennsieve,
    extract_numeric_value,
    load_yaml_mappings,
    normalize_column_name,
    read_csv_with_fallback,
)

# Dataset configuration
DATASET_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'
DATA_DIR = pathlib.Path(__file__).parent / 'data'
CACHE_DIR = DATA_DIR / 'csv_cache' / DATASET_UUID


class F006Ingestion(GenericStudyIngestion):
    """F006-specific implementation of the generic study ingestion."""

    def __init__(self):
        # Load both common and F006-specific mappings
        base_mappings_file = pathlib.Path(__file__).parent / 'study_template_mappings.yaml'
        f006_mappings_file = pathlib.Path(__file__).parent / 'f006_interlex_mappings.yaml'

        # Load and merge mappings
        mappings = load_yaml_mappings(str(base_mappings_file), str(f006_mappings_file))

        # Initialize with merged mappings
        super().__init__(DATASET_UUID, None)
        self.mappings = mappings
        self.cache_dir = CACHE_DIR

    def parse_path_structure(self, path_parts: List[str]) -> Dict[str, Any]:
        """
        Parse F006-specific path structure.

        F006 has structure like:
        - sub-{species}###-{sex}###/sam-{sample}[sidedness]/
        - derivatives/sub-{species}###-{sex}###/sam-{sample}[sidedness]/

        Returns:
            Dictionary with subject_id, sample_id, sidedness, etc.
        """
        result = {}

        # Join parts to get full path for pattern matching
        full_path = '/'.join(path_parts)

        # Extract subject information
        sub_match = re.search(r'sub-(\w+)(\d+)-(\w+)(\d+)', full_path)
        if sub_match:
            species = sub_match.group(1)
            species_num = sub_match.group(2)
            sex = sub_match.group(3)
            sex_num = sub_match.group(4)
            result['subject_id'] = f'sub-{species}{species_num}-{sex}{sex_num}'
            result['species'] = species
            result['sex'] = sex

        # Extract sample information
        sam_match = re.search(r'sam-(\w+)([lr]?)', full_path)
        if sam_match:
            sample_name = sam_match.group(1)
            sidedness = sam_match.group(2)
            result['sample_id'] = f'sam-{sample_name}{sidedness}'
            result['sample_type'] = self._get_sample_type(sample_name)
            if sidedness:
                result['sidedness'] = 'left' if sidedness == 'l' else 'right'

        # Check if it's derivatives
        if 'derivatives' in path_parts:
            result['is_derivative'] = True

        # Extract file type information
        if path_parts and path_parts[-1].endswith('.csv'):
            filename = path_parts[-1]
            if 'fascicles' in filename:
                result['data_type'] = 'fascicle'
            elif 'fibers' in filename:
                result['data_type'] = 'fiber'

        return result

    def _get_sample_type(self, sample_name: str) -> str:
        """Map sample names to sample types."""
        # F006 specific nerve mappings
        nerve_mappings = {
            'vagus': 'nerve-volume',
            'pelvic': 'nerve-volume',
            'femoral': 'nerve-volume',
            'sciatic': 'nerve-volume',
            'pudendal': 'nerve-volume',
            'splanchnic': 'nerve-volume',
            'hypogastric': 'nerve-volume',
            'lumbar': 'nerve-volume',
            'tibial': 'nerve-volume',
            'peroneal': 'nerve-volume',
        }

        for nerve, sample_type in nerve_mappings.items():
            if nerve in sample_name.lower():
                return sample_type

        return 'nerve-volume'  # Default

    def process_data_file(
        self, file_info: Dict[str, Any], session: Session, components: Dict[str, Any], instances: Dict[str, Any]
    ) -> List[Any]:
        """
        Process F006 CSV files and create values.

        Args:
            file_info: Metadata about the file
            session: Database session
            components: Dictionary of created components
            instances: Dictionary of created instances

        Returns:
            List of created value objects
        """
        values = []

        # Check if it's a CSV file
        if not file_info.get('mimetype') == 'text/csv':
            return values

        # Parse the path to understand what kind of data this is
        path_parts = pathlib.Path(file_info['dataset_relative_path']).parts
        parsed = self.parse_path_structure(list(path_parts))

        if not parsed:
            return values

        # Download the CSV file if needed
        from quantdb.pennsieve_client import PennsieveClient

        client = PennsieveClient()

        csv_path = download_csv_from_pennsieve(client, file_info, cache_dir=self.cache_dir)

        if not csv_path:
            print(f"Failed to download CSV: {file_info['dataset_relative_path']}")
            return values

        # Read the CSV data
        try:
            df = read_csv_with_fallback(str(csv_path))
        except Exception as e:
            print(f'Error reading CSV {csv_path}: {e}')
            return values

        # Get the relevant instances
        subject_id = parsed.get('subject_id')
        sample_id = parsed.get('sample_id')

        subject_inst = instances.get(subject_id)
        sample_key = f'{subject_id}_{sample_id}' if subject_id and sample_id else None
        sample_inst = instances.get(sample_key) if sample_key else None

        if not sample_inst:
            print(f'No sample instance found for {sample_key}')
            return values

        # Process based on data type
        data_type = parsed.get('data_type', '')

        if data_type == 'fascicle':
            values.extend(self._process_fascicle_csv(df, session, components, sample_inst))
        elif data_type == 'fiber':
            values.extend(self._process_fiber_csv(df, session, components, sample_inst))

        return values

    def _process_fascicle_csv(
        self, df: pd.DataFrame, session: Session, components: Dict[str, Any], sample_inst: ValuesInst
    ) -> List[Any]:
        """Process fascicle CSV data."""
        values = []

        # Get descriptors
        fasc_desc = components.get('descriptors_inst', {}).get('fascicle-cross-section')
        if not fasc_desc:
            print('Missing fascicle-cross-section descriptor')
            return values

        # Process each row as a fascicle
        for idx, row in df.iterrows():
            # Create fascicle instance
            fascicle_id = row.get('fascicle', idx)
            fascicle_inst = ValuesInst(
                type='site',
                desc_inst=fasc_desc.id,
                dataset=sample_inst.dataset,
                id_formal=f'fascicle-{fascicle_id}',
                id_sub=sample_inst.id_sub,
                id_sam=sample_inst.id_sam,
            )
            fascicle_inst.descriptors_inst = fasc_desc
            fascicle_inst.objects = sample_inst.objects

            fascicle_result = get_or_create(session, fascicle_inst)

            # Create quantitative values for fascicle measurements
            quant_mappings = {
                'area': 'fascicle cross section area um2',
                'eff_diam': 'fascicle cross section diameter um',
                'shortest_diameter': 'fascicle cross section diameter um min',
                'longest_diameter': 'fascicle cross section diameter um max',
                'x_cent': 'fascicle centroid x position um',
                'y_cent': 'fascicle centroid y position um',
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

            for col_name, desc_label in quant_mappings.items():
                if col_name in row and pd.notna(row[col_name]):
                    desc = components.get('descriptors_quant', {}).get(desc_label)
                    if desc:
                        value_num = extract_numeric_value(row[col_name])
                        if value_num is not None:
                            quant_value = ValuesQuant(
                                desc_quant=desc.id, value_instance=fascicle_result.id, value=value_num
                            )
                            quant_value.descriptors_quant = desc
                            quant_value.values_inst = fascicle_result

                            result = get_or_create(session, quant_value)
                            values.append(result)

        return values

    def _process_fiber_csv(
        self, df: pd.DataFrame, session: Session, components: Dict[str, Any], sample_inst: ValuesInst
    ) -> List[Any]:
        """Process fiber CSV data."""
        values = []

        # Get descriptors
        fiber_desc = components.get('descriptors_inst', {}).get('fiber-cross-section')
        fasc_desc = components.get('descriptors_inst', {}).get('fascicle-cross-section')

        if not fiber_desc:
            print('Missing fiber-cross-section descriptor')
            return values

        # Group by fascicle to create parent instances
        fascicle_instances = {}

        for fascicle_id in df['fascicle'].unique():
            if pd.notna(fascicle_id):
                # Create or get fascicle instance
                fascicle_inst = ValuesInst(
                    type='site',
                    desc_inst=fasc_desc.id,
                    dataset=sample_inst.dataset,
                    id_formal=f'fascicle-{fascicle_id}',
                    id_sub=sample_inst.id_sub,
                    id_sam=sample_inst.id_sam,
                )
                fascicle_inst.descriptors_inst = fasc_desc
                fascicle_inst.objects = sample_inst.objects

                fascicle_result = get_or_create(session, fascicle_inst)
                fascicle_instances[fascicle_id] = fascicle_result

        # Process each fiber
        for idx, row in df.iterrows():
            # Skip if no fascicle assignment
            fascicle_id = row.get('fascicle')
            if pd.isna(fascicle_id):
                continue

            # Create fiber instance
            fiber_inst = ValuesInst(
                type='instance',
                desc_inst=fiber_desc.id,
                dataset=sample_inst.dataset,
                id_formal=f'fiber-{idx}',
                id_sub=sample_inst.id_sub,
                id_sam=sample_inst.id_sam,
            )
            fiber_inst.descriptors_inst = fiber_desc
            fiber_inst.objects = sample_inst.objects

            fiber_result = get_or_create(session, fiber_inst)

            # Create quantitative values for fiber measurements
            quant_mappings = {
                'fiber_area': 'fiber cross section area um2',
                'eff_fib_diam': 'fiber cross section diameter um',
                'shortest_diameter': 'fiber cross section diameter um min',
                'longest_diameter': 'fiber cross section diameter um max',
                'x': 'fiber centroid x position um',
                'y': 'fiber centroid y position um',
                'rho': 'fiber radius from fascicle centroid um',
                'phi': 'fiber angle from fascicle centroid radians',
            }

            for col_name, desc_label in quant_mappings.items():
                if col_name in row and pd.notna(row[col_name]):
                    desc = components.get('descriptors_quant', {}).get(desc_label)
                    if desc:
                        value_num = extract_numeric_value(row[col_name])
                        if value_num is not None:
                            quant_value = ValuesQuant(
                                desc_quant=desc.id, value_instance=fiber_result.id, value=value_num
                            )
                            quant_value.descriptors_quant = desc
                            quant_value.values_inst = fiber_result

                            result = get_or_create(session, quant_value)
                            values.append(result)

            # Create categorical values for fiber classification
            cat_mappings = {
                'myelinated': ('myelin status', 'myelinated', 'unmyelinated'),
                'nav': ('marker expression', 'nav-positive', None),
                'chat': ('marker expression', 'chat-positive', None),
            }

            for col_name, (desc_label, true_term, false_term) in cat_mappings.items():
                if col_name in row and pd.notna(row[col_name]):
                    desc = components.get('descriptors_cat', {}).get(desc_label)
                    if desc:
                        # Determine the term based on boolean value
                        if row[col_name] in [1, '1', True, 'true', 'True']:
                            term_label = true_term
                        elif false_term and row[col_name] in [0, '0', False, 'false', 'False']:
                            term_label = false_term
                        else:
                            continue

                        term = components.get('terms', {}).get(term_label)
                        if term:
                            cat_value = ValuesCat(desc_cat=desc.id, value_instance=fiber_result.id, value=term.id)
                            cat_value.descriptors_cat = desc
                            cat_value.values_inst = fiber_result
                            cat_value.controlled_terms = term

                            result = get_or_create(session, cat_value)
                            values.append(result)

            # Check fiber type classification
            fiber_type = None
            if row.get('a_alpha') in [1, '1', True]:
                fiber_type = 'a-alpha-fiber'
            elif row.get('a_beta') in [1, '1', True]:
                fiber_type = 'a-beta-fiber'
            elif row.get('a_gamma') in [1, '1', True]:
                fiber_type = 'a-gamma-fiber'
            elif row.get('a_delta') in [1, '1', True]:
                fiber_type = 'a-delta-fiber'
            elif row.get('b') in [1, '1', True]:
                fiber_type = 'b-fiber'
            elif row.get('unmyel_nf') in [1, '1', True]:
                fiber_type = 'c-fiber'

            if fiber_type:
                desc = components.get('descriptors_cat', {}).get('fiber type classification')
                term = components.get('terms', {}).get(fiber_type)
                if desc and term:
                    cat_value = ValuesCat(desc_cat=desc.id, value_instance=fiber_result.id, value=term.id)
                    cat_value.descriptors_cat = desc
                    cat_value.values_inst = fiber_result
                    cat_value.controlled_terms = term

                    result = get_or_create(session, cat_value)
                    values.append(result)

        return values


def run_f006_ingestion(session=None, test=True):
    """
    Run the F006 ingestion using the generic template.

    Args:
        session: Optional database session
        test: Whether to use test database
    """
    ingestion = F006Ingestion()
    ingestion.ingest(session=session, test=test)


if __name__ == '__main__':
    # Run with test database by default
    run_f006_ingestion(test=True)
