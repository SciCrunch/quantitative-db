#!/usr/bin/env python3
"""
Generic Study Ingestion following the new ingest.py pattern

This module provides a base class for dataset ingestion that follows the value-generating
function pattern used in the main ingest.py module. It's designed to be more efficient
and consistent with the main ingestion pipeline.

The ingestion flow:
1. Extract function returns tuple of value-generating functions
2. Ingest function uses these to populate database with batch inserts
"""

import json
import pathlib
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from sparcur.utils import PennsieveId as RemoteId

from quantdb.ingest import (
    InternalIds,
    Queries,
    ingest,
    sort_parents,
    values_objects_from_objects,
)
from quantdb.utils import log


class GenericStudyIngest(ABC):
    """
    Base class for dataset-specific ingestion using the new pattern.

    This class provides the framework for creating extract functions that
    return value-generating functions for use with the main ingest function.
    """

    def __init__(self, dataset_uuid: str, mappings_file: Optional[str] = None):
        """
        Initialize the ingestion with dataset UUID and optional mappings file.

        Args:
            dataset_uuid: UUID of the dataset to ingest
            mappings_file: Path to YAML file containing descriptor mappings
        """
        self.dataset_uuid = uuid.UUID(dataset_uuid) if isinstance(dataset_uuid, str) else dataset_uuid
        self.dataset_id = RemoteId('dataset:' + str(dataset_uuid))
        self.mappings = {}

        if mappings_file:
            with open(mappings_file, 'r') as f:
                self.mappings = yaml.safe_load(f)

    @abstractmethod
    def parse_path_structure(self, path_parts: List[str]) -> Dict[str, Any]:
        """
        Parse dataset-specific path structure to extract metadata.

        Args:
            path_parts: List of path components from dataset_relative_path

        Returns:
            Dictionary containing extracted metadata (subject_id, sample_id, etc.)
        """
        pass

    @abstractmethod
    def process_data_file(
        self,
        file_info: Dict[str, Any],
        instances: Dict,
        parents: List,
        quantitative_values: List,
        categorical_values: List,
    ) -> None:
        """
        Process a specific data file and update value collections.

        Args:
            file_info: Metadata about the file from path-metadata.json
            instances: Dictionary to update with instances
            parents: List to update with parent relationships
            quantitative_values: List to update with quantitative values
            categorical_values: List to update with categorical values
        """
        pass

    def load_metadata(self, metadata_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load path metadata from JSON file.

        Args:
            metadata_path: Path to metadata file (defaults to standard location)

        Returns:
            Parsed metadata dictionary
        """
        if metadata_path:
            with open(metadata_path, 'r') as f:
                return json.load(f)

        # Default to loading from standard data directory
        data_dir = pathlib.Path(__file__).parent / 'data'
        metadata_file = data_dir / f'{self.dataset_uuid}_path_metadata.json'

        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                return json.load(f)

        raise FileNotFoundError(f'Metadata file not found: {metadata_file}')

    def extract(self, source_local: bool = True, visualize: bool = False) -> Tuple:
        """
        Main extraction function that returns value-generating functions.

        This is the key method that follows the new ingest.py pattern.

        Returns:
            Tuple of (updated_transitive, values_objects, values_dataset_object,
                     make_values_instances, make_values_parents, make_void,
                     make_vocd, make_voqd, make_values_cat, make_values_quant)
        """
        # Load metadata
        metadata = self.load_metadata()

        # Initialize collections
        instances = {}
        parents = []
        objects = {}

        # Collections for different value types
        quantitative_values = []
        categorical_values = []

        # Process each file in metadata
        for file_info in metadata.get('data', []):
            # Parse path structure
            path = file_info.get('dataset_relative_path', '')
            path_parts = path.split('/')
            path_data = self.parse_path_structure(path_parts)

            # Create subject/sample instances if needed
            if path_data.get('subject_id'):
                id_sub = path_data['subject_id']
                if (self.dataset_id, id_sub) not in instances:
                    instances[(self.dataset_id, id_sub)] = {
                        'type': 'subject',
                        'desc_inst': 'subject',
                        'id_sub': id_sub,
                        'id_sam': None,
                    }

            if path_data.get('sample_id'):
                id_sam = path_data['sample_id']
                id_sub = path_data.get('subject_id')
                if (self.dataset_id, id_sam) not in instances:
                    instances[(self.dataset_id, id_sam)] = {
                        'type': 'sample',
                        'desc_inst': self._get_sample_descriptor(path_data),
                        'id_sub': id_sub,
                        'id_sam': id_sam,
                    }
                    if id_sub:
                        parents.append((self.dataset_id, id_sam, id_sub))

            # Add file object if it has remote_id
            if 'remote_id' in file_info:
                obj_uuid = file_info['remote_id'].split(':')[-1]
                obj_file_id = file_info.get('file_id')
                objects[obj_uuid] = {'id_type': 'package', 'id_file': obj_file_id}

            # Process data file
            self.process_data_file(file_info, instances, parents, quantitative_values, categorical_values)

        # Sort parents for proper ordering
        parents = sort_parents(parents)

        # Prepare return values
        updated_transitive = None
        values_objects = values_objects_from_objects(objects)
        values_dataset_object = [(str(self.dataset_uuid), obj_uuid) for obj_uuid in objects.keys()]

        # Create value-generating functions
        make_values_instances = self._make_values_instances_factory(instances)
        make_values_parents = self._make_values_parents_factory(parents)
        make_void = self._make_void_factory(objects)
        make_vocd = self._make_vocd_factory(objects)
        make_voqd = self._make_voqd_factory(objects)
        make_values_cat = self._make_values_cat_factory(categorical_values)
        make_values_quant = self._make_values_quant_factory(quantitative_values)

        return (
            updated_transitive,
            values_objects,
            values_dataset_object,
            make_values_instances,
            make_values_parents,
            make_void,
            make_vocd,
            make_voqd,
            make_values_cat,
            make_values_quant,
        )

    def _get_sample_descriptor(self, path_data: Dict[str, Any]) -> str:
        """Get the appropriate descriptor for a sample based on path data."""
        sample_type = path_data.get('sample_type', '')
        if 'nerve' in sample_type:
            return 'nerve-cross-section'
        elif 'brain' in sample_type:
            return 'brain-region'
        else:
            return 'sample'

    def _make_values_instances_factory(self, instances: Dict) -> Callable:
        """Create the make_values_instances function."""

        def make_values_instances(i):
            values_instances = [
                (
                    d.uuid,
                    f,
                    inst['type'],
                    i.luid[inst['desc_inst']],
                    inst['id_sub'] if 'id_sub' in inst else None,
                    inst['id_sam'] if 'id_sam' in inst else None,
                )
                for (d, f), inst in instances.items()
            ]
            return values_instances

        return make_values_instances

    def _make_values_parents_factory(self, parents: List) -> Callable:
        """Create the make_values_parents function."""

        def make_values_parents(luinst):
            values_parents = [(luinst[d.uuid, child], luinst[d.uuid, parent]) for d, child, parent in parents]
            return values_parents

        return make_values_parents

    def _make_void_factory(self, objects: Dict) -> Callable:
        """Create the make_void function."""

        def make_void(this_dataset_updated_uuid, i):
            void = []
            # Override in subclass for specific descriptor-object mappings
            return void

        return make_void

    def _make_vocd_factory(self, objects: Dict) -> Callable:
        """Create the make_vocd function."""

        def make_vocd(this_dataset_updated_uuid, i):
            vocd = []
            # Override in subclass for categorical descriptor-object mappings
            return vocd

        return make_vocd

    def _make_voqd_factory(self, objects: Dict) -> Callable:
        """Create the make_voqd function."""

        def make_voqd(this_dataset_updated_uuid, i):
            voqd = []
            # Override in subclass for quantitative descriptor-object mappings
            return voqd

        return make_voqd

    def _make_values_cat_factory(self, categorical_values: List) -> Callable:
        """Create the make_values_cat function."""

        def make_values_cat(this_dataset_updated_uuid, i, luinst):
            values_cv = []
            # Process categorical values collected during extraction
            for cv in categorical_values:
                # Format: (value_open, value_controlled, object, desc_inst, desc_cat, instance)
                # Subclass should implement specific logic
                pass
            return values_cv

        return make_values_cat

    def _make_values_quant_factory(self, quantitative_values: List) -> Callable:
        """Create the make_values_quant function."""

        def make_values_quant(this_dataset_updated_uuid, i, luinst):
            values_qv = []
            # Process quantitative values collected during extraction
            for qv in quantitative_values:
                id_formal = qv.get('id_formal')
                if id_formal and (self.dataset_id.uuid, id_formal) in luinst:
                    instance_id = luinst[self.dataset_id.uuid, id_formal]

                    # Add each quantitative measurement
                    for key, value in qv.items():
                        if key not in ('id_formal', 'desc_inst'):
                            # Map key to descriptor
                            desc_label = self._map_to_descriptor(key)
                            if desc_label and value is not None:
                                values_qv.append(
                                    (
                                        value,
                                        None,  # object
                                        instance_id,
                                        i.reg_qd(desc_label),
                                        instance_id,
                                        None,  # value_blob
                                    )
                                )
            return values_qv

        return make_values_quant

    def _map_to_descriptor(self, key: str) -> Optional[str]:
        """Map a value key to a descriptor label."""
        # Override in subclass with specific mappings
        descriptor_map = {
            'area-um2': 'cross section area um2',
            'diameter-um': 'cross section diameter um',
            'volume-um3': 'volume um3',
            # Add more mappings as needed
        }
        return descriptor_map.get(key)

    def ingest(self, session, source_local: bool = True, commit: bool = False, dev: bool = False):
        """
        Run the ingestion using the new pattern.

        Args:
            session: Database session
            source_local: Whether to use local data sources
            commit: Whether to commit the transaction
            dev: Whether to run in development mode (ON CONFLICT DO NOTHING)
        """
        return ingest(str(self.dataset_uuid), self.extract, session, commit=commit, dev=dev, source_local=source_local)
