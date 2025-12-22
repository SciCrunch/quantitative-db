#!/usr/bin/env python3
"""
Generic Study Template for Dataset Ingestion

This module provides a base class and utilities for ingesting datasets into QuantDB
using a consistent pattern. Dataset-specific implementations should inherit from
GenericStudyIngestion and implement the abstract methods.

The ingestion flow follows these steps:
1. Load metadata and configuration
2. Create/verify root table entries (aspects, units, descriptors)
3. Create objects (dataset and packages)
4. Create instances (subjects, samples, sites, etc.)
5. Create mappings (ObjDesc* tables)
6. Create values (leaf tables with actual measurements)
"""

import json
import pathlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlalchemy.orm import Session

from quantdb.client import get_session
from quantdb.generic_ingest import get_or_create
from quantdb.ingest import InternalIds, Queries
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


class GenericStudyIngestion(ABC):
    """
    Base class for dataset-specific ingestion implementations.

    This class provides the framework for ingesting data following the QuantDB schema.
    Subclasses must implement abstract methods for dataset-specific logic.
    """

    def __init__(self, dataset_uuid: str, mappings_file: Optional[str] = None):
        """
        Initialize the ingestion with dataset UUID and optional mappings file.

        Args:
            dataset_uuid: UUID of the dataset to ingest
            mappings_file: Path to YAML file containing descriptor mappings
        """
        self.dataset_uuid = uuid.UUID(dataset_uuid) if isinstance(dataset_uuid, str) else dataset_uuid
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
        self, file_info: Dict[str, Any], session: Session, components: Dict[str, Any], instances: Dict[str, Any]
    ) -> List[Any]:
        """
        Process a specific data file and create values.

        Args:
            file_info: Metadata about the file from path-metadata.json
            session: Database session
            components: Dictionary of created components (descriptors, addresses, etc.)
            instances: Dictionary of created instances

        Returns:
            List of created value objects
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

    def create_base_components(self, session: Session) -> Dict[str, Any]:
        """
        Create base components from mappings (aspects, units, descriptors).

        Returns:
            Dictionary of created components
        """
        components = {'aspects': {}, 'units': {}, 'descriptors': {}, 'terms': {}, 'addresses': {}}

        # Create aspects
        if 'aspects' in self.mappings:
            for aspect_data in self.mappings['aspects']:
                aspect = Aspects(iri=aspect_data['iri'], label=aspect_data['label'])
                created = get_or_create(session, aspect)
                components['aspects'][aspect_data['label']] = created

        # Create units
        if 'units' in self.mappings:
            for unit_data in self.mappings['units']:
                unit = Units(iri=unit_data['iri'], label=unit_data['label'])
                created = get_or_create(session, unit)
                components['units'][unit_data['label']] = created

        # Create instance descriptors
        if 'descriptors' in self.mappings and 'instance_types' in self.mappings['descriptors']:
            for desc_data in self.mappings['descriptors']['instance_types']:
                desc = DescriptorsInst(iri=desc_data['iri'], label=desc_data['label'])
                created = get_or_create(session, desc)
                components['descriptors'][desc_data['label']] = created

        # Create controlled terms
        if 'controlled_terms' in self.mappings:
            for term_data in self.mappings['controlled_terms']:
                term = ControlledTerms(iri=term_data['iri'], label=term_data['label'])
                created = get_or_create(session, term)
                components['terms'][term_data['label']] = created

        # Create standard addresses
        const_addr = get_or_create(session, Addresses(addr_type='constant', addr_field=None, value_type='single'))
        components['addresses']['constant'] = const_addr

        return components

    def create_descriptors_from_mappings(self, session: Session, components: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create quantitative and categorical descriptors from mappings.
        """
        desc_components = {}

        # Create quantitative descriptors
        if 'descriptors' in self.mappings and 'quantitative' in self.mappings['descriptors']:
            for qd_data in self.mappings['descriptors']['quantitative']:
                domain_desc = components['descriptors'].get(qd_data['domain'])
                aspect = components['aspects'].get(qd_data['aspect'])
                unit = components['units'].get(qd_data['unit'])

                if domain_desc and aspect and unit:
                    qd = DescriptorsQuant(
                        shape=qd_data.get('shape', 'scalar'),
                        label=qd_data['label'],
                        aggregation_type=qd_data.get('aggregation_type', 'instance'),
                        unit=unit.id,
                        aspect=aspect.id,
                        domain=domain_desc.id,
                        description=qd_data.get('description', ''),
                    )
                    qd.units = unit
                    qd.aspects = aspect
                    qd.descriptors_inst = domain_desc

                    created = get_or_create(session, qd)
                    desc_components[qd_data['label']] = created

        # Create categorical descriptors
        if 'descriptors' in self.mappings and 'categorical' in self.mappings['descriptors']:
            for cd_data in self.mappings['descriptors']['categorical']:
                domain_desc = components['descriptors'].get(cd_data['domain'])

                if domain_desc:
                    cd = DescriptorsCat(
                        domain=domain_desc.id, range=cd_data.get('range', 'controlled'), label=cd_data['label']
                    )
                    cd.descriptors_inst = domain_desc

                    created = get_or_create(session, cd)
                    desc_components[cd_data['label']] = created

        return desc_components

    def create_objects(self, session: Session, metadata: Dict[str, Any]) -> Tuple[Objects, List[Objects]]:
        """
        Create dataset and package objects.

        Returns:
            Tuple of (dataset_object, list_of_package_objects)
        """
        # Create dataset object
        dataset_obj = Objects(id=self.dataset_uuid, id_type='dataset', id_file=None, id_internal=None)
        dataset_result = get_or_create(session, dataset_obj)

        # Create package objects based on file types defined in mappings
        package_objects = []
        file_types = self.mappings.get('file_types', {})

        for item in metadata.get('data', []):
            mimetype = item.get('mimetype')
            if mimetype in file_types:
                if not item.get('dataset_relative_path'):
                    continue

                package_id = uuid.uuid4()
                package_obj = Objects(
                    id=package_id, id_type='package', id_file=item.get('remote_inode_id'), id_internal=None
                )
                package_obj.objects_ = dataset_result

                package_result = get_or_create(session, package_obj)
                package_objects.append({'object': package_result, 'metadata': item, 'file_type': file_types[mimetype]})

        return dataset_result, package_objects

    def create_instances(
        self, session: Session, metadata: Dict[str, Any], dataset_obj: Objects, components: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create instances (subjects, samples, sites, etc.) from metadata.
        """
        instances = {}
        processed_ids = {'subjects': set(), 'samples': set(), 'sites': set()}

        for item in metadata.get('data', []):
            if not item.get('dataset_relative_path'):
                continue

            # Parse path to extract instance information
            path_parts = pathlib.Path(item['dataset_relative_path']).parts
            parsed = self.parse_path_structure(path_parts)

            if not parsed:
                continue

            # Create subject instance
            if 'subject_id' in parsed and parsed['subject_id'] not in processed_ids['subjects']:
                subject_type = self.mappings.get('instance_defaults', {}).get('subject_type', 'human')
                subject_desc = components['descriptors'].get(subject_type)

                if subject_desc:
                    subject_inst = ValuesInst(
                        type='subject',
                        desc_inst=subject_desc.id,
                        dataset=dataset_obj.id,
                        id_formal=parsed['subject_id'],
                        id_sub=parsed['subject_id'],
                        id_sam=None,
                    )
                    subject_inst.objects = dataset_obj
                    subject_inst.descriptors_inst = subject_desc

                    result = get_or_create(session, subject_inst)
                    instances[parsed['subject_id']] = result
                    processed_ids['subjects'].add(parsed['subject_id'])

            # Create sample instance
            if 'sample_id' in parsed:
                sample_key = f"{parsed.get('subject_id', '')}_{parsed['sample_id']}"
                if sample_key not in processed_ids['samples']:
                    sample_type = parsed.get(
                        'sample_type', self.mappings.get('instance_defaults', {}).get('sample_type', 'nerve-volume')
                    )
                    sample_desc = components['descriptors'].get(sample_type)

                    if sample_desc:
                        sample_inst = ValuesInst(
                            type='sample',
                            desc_inst=sample_desc.id,
                            dataset=dataset_obj.id,
                            id_formal=parsed['sample_id'],
                            id_sub=parsed.get('subject_id'),
                            id_sam=parsed['sample_id'],
                        )
                        sample_inst.objects = dataset_obj
                        sample_inst.descriptors_inst = sample_desc

                        result = get_or_create(session, sample_inst)
                        instances[sample_key] = result
                        processed_ids['samples'].add(sample_key)

            # Create site instance if applicable
            if 'site_id' in parsed and parsed['site_id']:
                site_key = f"{parsed.get('subject_id', '')}_{parsed.get('sample_id', '')}_{parsed['site_id']}"
                if site_key not in processed_ids['sites']:
                    site_type = parsed.get(
                        'site_type', self.mappings.get('instance_defaults', {}).get('site_type', 'extruded-plane')
                    )
                    site_desc = components['descriptors'].get(site_type)

                    if site_desc:
                        site_inst = ValuesInst(
                            type='site',
                            desc_inst=site_desc.id,
                            dataset=dataset_obj.id,
                            id_formal=parsed['site_id'],
                            id_sub=parsed.get('subject_id'),
                            id_sam=parsed.get('sample_id'),
                        )
                        site_inst.objects = dataset_obj
                        site_inst.descriptors_inst = site_desc

                        result = get_or_create(session, site_inst)
                        instances[site_key] = result
                        processed_ids['sites'].add(site_key)

        return instances

    def create_mappings(
        self, session: Session, components: Dict[str, Any], package_objects: List[Dict[str, Any]]
    ) -> Dict[str, List[Any]]:
        """
        Create ObjDesc* mappings based on configuration.
        """
        mappings = {'obj_desc_inst': [], 'obj_desc_cat': [], 'obj_desc_quant': []}

        mapping_config = self.mappings.get('object_mappings', {})

        for pkg_info in package_objects:
            package = pkg_info['object']
            file_type = pkg_info['file_type']

            # Get mappings for this file type
            if file_type in mapping_config:
                config = mapping_config[file_type]

                # Create ObjDescInst mappings
                for inst_mapping in config.get('instance_mappings', []):
                    desc = components['descriptors'].get(inst_mapping['descriptor'])
                    addr = components['addresses'].get(inst_mapping.get('address', 'constant'))

                    if desc and addr:
                        obj_desc_inst = ObjDescInst(object=package.id, desc_inst=desc.id, addr_field=addr.id)
                        obj_desc_inst.objects = package
                        obj_desc_inst.descriptors_inst = desc
                        obj_desc_inst.addresses_field = addr

                        result = get_or_create(session, obj_desc_inst)
                        mappings['obj_desc_inst'].append(result)

                # Create ObjDescCat mappings
                for cat_mapping in config.get('categorical_mappings', []):
                    desc = components.get(cat_mapping['descriptor'])
                    addr = components['addresses'].get(cat_mapping.get('address', 'constant'))

                    if desc and addr:
                        obj_desc_cat = ObjDescCat(object=package.id, desc_cat=desc.id, addr_field=addr.id)
                        obj_desc_cat.objects = package
                        obj_desc_cat.descriptors_cat = desc
                        obj_desc_cat.addresses_ = addr

                        result = get_or_create(session, obj_desc_cat)
                        mappings['obj_desc_cat'].append(result)

                # Create ObjDescQuant mappings
                for quant_mapping in config.get('quantitative_mappings', []):
                    desc = components.get(quant_mapping['descriptor'])
                    addr = components['addresses'].get(quant_mapping.get('address', 'constant'))

                    if desc and addr:
                        obj_desc_quant = ObjDescQuant(object=package.id, desc_quant=desc.id, addr_field=addr.id)
                        obj_desc_quant.objects = package
                        obj_desc_quant.descriptors_quant = desc
                        obj_desc_quant.addresses_field = addr

                        result = get_or_create(session, obj_desc_quant)
                        mappings['obj_desc_quant'].append(result)

        return mappings

    def create_values(
        self,
        session: Session,
        metadata: Dict[str, Any],
        components: Dict[str, Any],
        package_objects: List[Dict[str, Any]],
        instances: Dict[str, Any],
    ) -> Dict[str, List[Any]]:
        """
        Create value entries by processing data files.
        """
        values = {'values_cat': [], 'values_quant': []}

        # Merge base components with descriptor components
        all_components = {**components}
        if hasattr(self, 'descriptor_components'):
            all_components.update(self.descriptor_components)

        # Process each package/file
        for pkg_info in package_objects:
            file_values = self.process_data_file(pkg_info['metadata'], session, all_components, instances)

            for value in file_values:
                if isinstance(value, ValuesCat):
                    values['values_cat'].append(value)
                elif isinstance(value, ValuesQuant):
                    values['values_quant'].append(value)

        return values

    def ingest(self, session: Optional[Session] = None, test: bool = True):
        """
        Run the complete ingestion pipeline.

        Args:
            session: Database session (creates new if not provided)
            test: Whether to use test database
        """
        if session is None:
            session = get_session(test=test)

        try:
            print(f'Starting ingestion for dataset: {self.dataset_uuid}')

            # Step 1: Load metadata
            print('Loading metadata...')
            metadata = self.load_metadata()

            # Step 2: Create base components
            print('Creating base components...')
            components = self.create_base_components(session)

            # Step 3: Create descriptors from mappings
            print('Creating descriptors...')
            self.descriptor_components = self.create_descriptors_from_mappings(session, components)

            # Step 4: Create objects
            print('Creating objects...')
            dataset_obj, package_objects = self.create_objects(session, metadata)

            # Step 5: Create instances
            print('Creating instances...')
            instances = self.create_instances(session, metadata, dataset_obj, components)

            # Step 6: Create mappings
            print('Creating mappings...')
            mappings = self.create_mappings(session, components, package_objects)

            # Step 7: Create values
            print('Creating values...')
            values = self.create_values(session, metadata, components, package_objects, instances)

            # Commit all changes
            session.commit()

            print(f'Ingestion complete!')
            print(f'Created {len(instances)} instances')
            print(f"Created {len(values['values_cat'])} categorical values")
            print(f"Created {len(values['values_quant'])} quantitative values")

        except Exception as e:
            session.rollback()
            print(f'Error during ingestion: {e}')
            raise
        finally:
            if session:
                session.close()


# Example usage in dataset-specific implementation:
# class F006Ingestion(GenericStudyIngestion):
#     def parse_path_structure(self, path_parts):
#         # F006-specific implementation
#         pass
#
#     def process_data_file(self, file_info, session, components, instances):
#         # F006-specific implementation
#         pass
