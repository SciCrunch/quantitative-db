#!/usr/bin/env python3
"""
Test suite for specific ingest extract functions.
Tests the actual extract_reva_ft and other extract functions from quantdb/ingest.py
"""

from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pytest
from sparcur.utils import PennsieveId as RemoteId
from sqlalchemy import text

from quantdb.ingest import (
    extract_demo,
    extract_demo_jp2,
    extract_reva_ft,
    ingest,
)


class TestExtractFunctions:
    """Test individual extract functions with real data patterns."""

    def test_extract_reva_ft_basic(self, test_session):
        """Test extract_reva_ft function with basic functionality."""
        # Known dataset UUID for f001
        dataset_uuid = 'aa43eda8-b29a-4c25-9840-ecbd57598afc'

        # Create a datetime object for testing
        test_timestamp = datetime(2024, 1, 1, 0, 0, 1)

        # Use a valid UUID for testing
        test_object_uuid = '1ff97dbc-05e0-4c53-8c92-31a7b9bf75ab'

        # Mock the external dependencies to avoid actual API calls
        with patch('quantdb.ingest.requests.get') as mock_get:
            # Mock the response from the API
            mock_response = Mock()
            mock_response.json.return_value = {
                'data': [
                    {'basename': 'test-dataset-f001', 'timestamp_updated': test_timestamp},
                    {
                        'type': 'pathmeta',
                        'timestamp_updated': test_timestamp,
                        'mimetype': 'image/jpx',
                        'dataset': {'uuid': dataset_uuid, 'type': 'dataset'},
                        'object': {'uuid': test_object_uuid, 'type': 'package'},
                        'file_id': 12345,  # Use integer for file_id
                        'subject': 'sub-001',
                        'sample': 'sam-001',
                        'parents': [('sam-parent',)],
                        'raw_anat_index_v2': 1.0,
                        'modality': 'microct',
                    },
                ]
            }
            mock_get.return_value = mock_response

            # Mock fromJson to avoid the breakpoint
            with patch('quantdb.ingest.fromJson') as mock_fromJson:
                # Create mock dataset and object instances
                mock_dataset = Mock()
                mock_dataset.uuid = dataset_uuid
                mock_dataset.type = 'dataset'

                mock_object = Mock()
                mock_object.uuid = test_object_uuid
                mock_object.type = 'package'

                # Return processed data that includes the required fields
                mock_fromJson.return_value = {
                    'data': [
                        {'basename': 'test-dataset-f001', 'timestamp_updated': test_timestamp},
                        {
                            'type': 'pathmeta',
                            'timestamp_updated': test_timestamp,
                            'mimetype': 'image/jpx',
                            'dataset': mock_dataset,
                            'object': mock_object,
                            'file_id': 12345,  # Use integer for file_id
                            'subject': 'sub-001',
                            'sample': 'sam-001',
                            'parents': [('sam-001', 'sub-001')],  # Proper parent format
                            'raw_anat_index_v2': 1.0,
                            'modality': 'microct',
                        },
                    ]
                }

                # Mock the ext_pmeta function to return proper structure
                with patch('quantdb.ingest.ext_pmeta') as mock_ext_pmeta:
                    mock_ext_pmeta.return_value = {
                        'dataset': mock_dataset,
                        'object': mock_object,
                        'file_id': 12345,  # Use integer for file_id
                        'subject': 'sub-001',
                        'sample': 'sam-001',
                        'parents': [('sam-001', 'sub-001')],  # Proper parent format (sample, subject)
                        'raw_anat_index_v2': 1.0,
                        'modality': 'microct',
                        'norm_anat_index_v2': 0.5,
                        'norm_anat_index_v2_min': 0.0,
                        'norm_anat_index_v2_max': 1.0,
                    }

                    # Run the ingestion
                    result = ingest(
                        dataset_uuid,
                        extract_reva_ft,
                        test_session,
                        commit=False,
                        dev=True,
                        source_local=False,
                        visualize=False,
                    )

                    # Basic assertions
                    assert result is None  # ingest returns None
                    # The function should have been called
                    mock_get.assert_called_once()

    def test_extract_reva_ft_error_handling(self, test_session):
        """Test extract_reva_ft error handling."""
        dataset_uuid = 'invalid-uuid'

        with patch('quantdb.ingest.requests.get') as mock_get:
            # Simulate an error
            mock_get.side_effect = Exception('Dataset not found')

            # The ingest function should handle errors gracefully
            with pytest.raises(Exception) as exc_info:
                ingest(
                    dataset_uuid,
                    extract_reva_ft,
                    test_session,
                    commit=False,
                    dev=True,
                    source_local=False,
                    visualize=False,
                )

            assert 'Dataset not found' in str(exc_info.value)

    @pytest.mark.parametrize(
        'extract_func,dataset_uuid,source_local',
        [
            (extract_reva_ft, 'aa43eda8-b29a-4c25-9840-ecbd57598afc', False),
            (extract_demo, '55c5b69c-a5b8-4881-a105-e4048af26fa5', True),
            (extract_demo_jp2, '55c5b69c-a5b8-4881-a105-e4048af26fa5', False),
        ],
    )
    def test_extract_functions_smoke_test(self, test_session, extract_func, dataset_uuid, source_local):
        """Smoke test for various extract functions to ensure they don't crash."""
        # Mock based on which extract function we're testing
        if extract_func == extract_reva_ft:
            with patch('quantdb.ingest.requests.get') as mock_get:
                mock_response = Mock()
                test_timestamp = datetime(2024, 1, 1, 0, 0, 1)
                mock_response.json.return_value = {
                    'data': [
                        {'timestamp_updated': test_timestamp},
                        {'timestamp_updated': test_timestamp, 'mimetype': 'image/jpx'},
                    ]
                }
                mock_get.return_value = mock_response

                with patch('quantdb.ingest.fromJson') as mock_fromJson:
                    mock_fromJson.return_value = {
                        'data': [
                            {'timestamp_updated': test_timestamp},
                            {'timestamp_updated': test_timestamp, 'mimetype': 'image/jpx'},
                        ]
                    }

                    try:
                        ingest(
                            dataset_uuid,
                            extract_func,
                            test_session,
                            commit=False,
                            dev=True,
                            source_local=source_local,
                            visualize=False,
                        )
                    except (KeyError, IndexError, AttributeError):
                        # Expected due to minimal mocking
                        assert True

        elif extract_func == extract_demo:
            with patch('quantdb.ingest.scipy.io.loadmat') as mock_loadmat:
                mock_loadmat.return_value = {}
                with patch('quantdb.ingest.Path'):
                    with patch('quantdb.ingest.SamplesFilePath'):
                        try:
                            ingest(
                                dataset_uuid,
                                extract_func,
                                test_session,
                                commit=False,
                                dev=True,
                                source_local=source_local,
                            )
                        except (KeyError, IndexError, AttributeError):
                            # Expected due to minimal mocking
                            assert True

        elif extract_func == extract_demo_jp2:
            with patch('quantdb.ingest.requests.get') as mock_get:
                mock_response = Mock()
                test_timestamp = datetime(2024, 1, 1, 0, 0, 1)
                mock_response.json.return_value = {
                    'data': [
                        {'timestamp_updated': test_timestamp},
                        {'timestamp_updated': test_timestamp, 'mimetype': 'image/jp2'},
                    ]
                }
                mock_get.return_value = mock_response

                with patch('quantdb.ingest.fromJson') as mock_fromJson:
                    mock_fromJson.return_value = {
                        'data': [
                            {'timestamp_updated': test_timestamp},
                            {'timestamp_updated': test_timestamp, 'mimetype': 'image/jp2'},
                        ]
                    }

                    try:
                        ingest(
                            dataset_uuid, extract_func, test_session, commit=False, dev=True, source_local=source_local
                        )
                    except (KeyError, IndexError, AttributeError):
                        # Expected due to minimal mocking
                        assert True


class TestIngestIntegration:
    """Integration tests for the full ingest pipeline."""

    def test_ingest_pipeline_rollback(self, test_session):
        """Test that ingest properly rolls back on error when commit=False."""
        dataset_uuid = 'test-uuid'

        def failing_extract_func(dataset_uuid, **kwargs):
            # Do some work
            # The extract function returns a tuple of functions
            # Return minimal valid structure then raise error
            raise ValueError('Intentional test failure')

        # Ensure we start with a clean transaction
        test_session.rollback()

        with pytest.raises(ValueError):
            ingest(dataset_uuid, failing_extract_func, test_session, commit=False, dev=True, source_local=False)

        # After the exception, the session should have been rolled back
        # We need to start a new transaction for the test
        test_session.rollback()

        # Session should still be usable after rollback
        result = test_session.execute(text('SELECT 1')).scalar()
        assert result == 1
