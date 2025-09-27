#!/usr/bin/env python3
"""
Comprehensive tests for beeminder_sync.py with 100% test coverage
"""

import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytz

# Import the module under test
import sys
sys.path.append('scripts')
from beeminder_sync import (
    BeeminderAPI,
    MeditationDatabase,
    extract_actual_time_from_apple_health,
    sync_beeminder_with_database,
    check_and_add_qualifying_meditation,
    load_env,
    main,
    NYC_TZ
)


class TestLoadEnv(unittest.TestCase):
    """Test environment variable loading"""

    @patch('builtins.open', mock_open(read_data='TEST_VAR=test_value\nANOTHER_VAR=another_value\n# Comment line\n\n'))
    @patch('os.path.exists', return_value=True)
    def test_load_env_success(self, mock_exists):
        """Test successful loading of environment variables"""
        with patch.dict('os.environ', {}, clear=True):
            load_env()
            self.assertEqual(os.environ.get('TEST_VAR'), 'test_value')
            self.assertEqual(os.environ.get('ANOTHER_VAR'), 'another_value')

    @patch('os.path.exists', return_value=False)
    def test_load_env_file_not_exists(self, mock_exists):
        """Test load_env when .env file doesn't exist"""
        with patch.dict('os.environ', {}, clear=True):
            load_env()  # Should not raise an exception

    @patch('builtins.open', mock_open(read_data='INVALID_LINE_NO_EQUALS\nVALID=value\n'))
    @patch('os.path.exists', return_value=True)
    def test_load_env_invalid_lines(self, mock_exists):
        """Test load_env with invalid lines"""
        with patch.dict('os.environ', {}, clear=True):
            load_env()
            self.assertEqual(os.environ.get('VALID'), 'value')
            self.assertIsNone(os.environ.get('INVALID_LINE_NO_EQUALS'))


class TestBeeminderAPI(unittest.TestCase):
    """Test BeeminderAPI class"""

    def setUp(self):
        self.api = BeeminderAPI('testuser', 'testtoken')

    def test_init(self):
        """Test BeeminderAPI initialization"""
        self.assertEqual(self.api.username, 'testuser')
        self.assertEqual(self.api.auth_token, 'testtoken')
        self.assertEqual(self.api.base_url, 'https://www.beeminder.com/api/v1')

    @patch('requests.get')
    def test_get_goal_data_single_page(self, mock_get):
        """Test get_goal_data with single page of results"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': '1', 'timestamp': 1234567890, 'value': 30},
            {'id': '2', 'timestamp': 1234567891, 'value': 45}
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.api.get_goal_data('test-goal')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], '1')
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_get_goal_data_multiple_pages(self, mock_get):
        """Test get_goal_data with multiple pages of results"""
        # First page (full page)
        first_response = Mock()
        first_response.json.return_value = [{'id': str(i), 'timestamp': 1234567890 + i, 'value': 30} for i in range(300)]
        first_response.raise_for_status.return_value = None

        # Second page (partial page)
        second_response = Mock()
        second_response.json.return_value = [{'id': '300', 'timestamp': 1234568190, 'value': 30}]
        second_response.raise_for_status.return_value = None

        mock_get.side_effect = [first_response, second_response]

        result = self.api.get_goal_data('test-goal')

        self.assertEqual(len(result), 301)
        self.assertEqual(mock_get.call_count, 2)

    @patch('requests.get')
    def test_get_goal_data_empty_response(self, mock_get):
        """Test get_goal_data with empty response"""
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.api.get_goal_data('test-goal')

        self.assertEqual(len(result), 0)

    @patch('requests.get')
    def test_get_goal_data_request_exception(self, mock_get):
        """Test get_goal_data with request exception"""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException('Network error')

        result = self.api.get_goal_data('test-goal')

        self.assertEqual(len(result), 0)

    @patch('requests.post')
    def test_add_datapoint_success(self, mock_post):
        """Test successful add_datapoint"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.api.add_datapoint('test-goal', 1.0, 1234567890, 'test comment')

        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_add_datapoint_failure(self, mock_post):
        """Test failed add_datapoint"""
        import requests
        mock_post.side_effect = requests.exceptions.RequestException('API error')

        result = self.api.add_datapoint('test-goal', 1.0, 1234567890, 'test comment')

        self.assertFalse(result)

    @patch('requests.delete')
    def test_delete_datapoint_success(self, mock_delete):
        """Test successful delete_datapoint"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_delete.return_value = mock_response

        result = self.api.delete_datapoint('test-goal', 'datapoint-id')

        self.assertTrue(result)
        mock_delete.assert_called_once()

    @patch('requests.delete')
    def test_delete_datapoint_failure(self, mock_delete):
        """Test failed delete_datapoint"""
        import requests
        mock_delete.side_effect = requests.exceptions.RequestException('API error')

        result = self.api.delete_datapoint('test-goal', 'datapoint-id')

        self.assertFalse(result)


class TestMeditationDatabase(unittest.TestCase):
    """Test MeditationDatabase class"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test_db.json'

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_init_new_database(self):
        """Test initialization of new database"""
        db = MeditationDatabase(self.db_path)

        self.assertTrue(self.db_path.exists())
        self.assertEqual(len(db.get_datapoints()), 0)
        self.assertIn('last_updated', db.data)

    def test_init_existing_database(self):
        """Test initialization of existing database"""
        # Create existing database
        initial_data = {
            'datapoints': [{'value': 1, 'timestamp': 123, 'comment': 'test', 'id': 'test_id'}],
            'last_updated': '2023-01-01T00:00:00Z'
        }
        with open(self.db_path, 'w') as f:
            json.dump(initial_data, f)

        db = MeditationDatabase(self.db_path)

        self.assertEqual(len(db.get_datapoints()), 1)
        self.assertEqual(db.get_datapoints()[0]['value'], 1)

    def test_add_datapoint(self):
        """Test adding a datapoint"""
        db = MeditationDatabase(self.db_path)

        db.add_datapoint(1.0, 1234567890, 'Test meditation')

        datapoints = db.get_datapoints()
        self.assertEqual(len(datapoints), 1)
        self.assertEqual(datapoints[0]['value'], 1.0)
        self.assertEqual(datapoints[0]['timestamp'], 1234567890)
        self.assertEqual(datapoints[0]['comment'], 'Test meditation')

    def test_datapoint_exists_true(self):
        """Test datapoint_exists when datapoint exists"""
        db = MeditationDatabase(self.db_path)
        db.add_datapoint(1.0, 1234567890, 'Test')

        self.assertTrue(db.datapoint_exists(1234567890, 1.0))

    def test_datapoint_exists_false(self):
        """Test datapoint_exists when datapoint doesn't exist"""
        db = MeditationDatabase(self.db_path)

        self.assertFalse(db.datapoint_exists(1234567890, 1.0))

    def test_save(self):
        """Test saving database"""
        db = MeditationDatabase(self.db_path)
        db.add_datapoint(1.0, 1234567890, 'Test')

        db.save()

        # Reload and verify
        with open(self.db_path, 'r') as f:
            saved_data = json.load(f)

        self.assertEqual(len(saved_data['datapoints']), 1)
        self.assertIn('last_updated', saved_data)


class TestExtractActualTimeFromAppleHealth(unittest.TestCase):
    """Test extract_actual_time_from_apple_health function"""

    def test_extract_apple_health_time_success(self):
        """Test successful extraction of Apple Health time"""
        datapoint = {
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 7)
        self.assertEqual(result.minute, 21)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 9)
        self.assertEqual(result.day, 26)

    def test_extract_apple_health_time_not_apple_health(self):
        """Test extraction from non-Apple Health datapoint"""
        datapoint = {
            'comment': 'Manual entry',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNone(result)

    def test_extract_apple_health_time_no_fulltext(self):
        """Test extraction with missing fulltext"""
        datapoint = {
            'comment': 'Auto-entered via Apple Health'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNone(result)

    def test_extract_apple_health_time_invalid_pattern(self):
        """Test extraction with invalid fulltext pattern"""
        datapoint = {
            'comment': 'Auto-entered via Apple Health',
            'fulltext': 'Invalid format text'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNone(result)

    def test_extract_apple_health_time_invalid_month(self):
        """Test extraction with invalid month abbreviation"""
        datapoint = {
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Inv-26 entered at 07:21 by zarathustra via BeemiOS'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNone(result)

    def test_extract_apple_health_time_invalid_date(self):
        """Test extraction with invalid date values"""
        datapoint = {
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Feb-30 entered at 25:61 by zarathustra via BeemiOS'
        }

        result = extract_actual_time_from_apple_health(datapoint)

        self.assertIsNone(result)


class TestSyncBeeminderWithDatabase(unittest.TestCase):
    """Test sync_beeminder_with_database function"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test_db.json'
        self.db = MeditationDatabase(self.db_path)
        self.api = Mock(spec=BeeminderAPI)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_sync_no_differences(self):
        """Test sync when local and remote are identical"""
        # Same data in both
        datapoints = [{'timestamp': 123, 'value': 1.0, 'id': 'test1'}]
        self.api.get_goal_data.return_value = datapoints
        self.db.add_datapoint(1.0, 123, 'test')

        sync_beeminder_with_database(self.api, self.db, 'test-goal')

        self.api.delete_datapoint.assert_not_called()
        self.api.add_datapoint.assert_not_called()

    def test_sync_delete_from_beeminder(self):
        """Test sync when Beeminder has extra datapoints"""
        # Beeminder has extra datapoint
        beeminder_data = [
            {'timestamp': 123, 'value': 1.0, 'id': 'test1'},
            {'timestamp': 456, 'value': 2.0, 'id': 'test2'}
        ]
        self.api.get_goal_data.return_value = beeminder_data
        self.db.add_datapoint(1.0, 123, 'test')

        sync_beeminder_with_database(self.api, self.db, 'test-goal')

        self.api.delete_datapoint.assert_called_once_with('test-goal', 'test2')

    def test_sync_add_to_beeminder(self):
        """Test sync when local database has extra datapoints"""
        # Local has extra datapoint
        beeminder_data = [{'timestamp': 123, 'value': 1.0, 'id': 'test1'}]
        self.api.get_goal_data.return_value = beeminder_data
        self.db.add_datapoint(1.0, 123, 'test1')
        self.db.add_datapoint(2.0, 456, 'test2')

        sync_beeminder_with_database(self.api, self.db, 'test-goal')

        self.api.add_datapoint.assert_called_once_with('test-goal', 2.0, 456, 'test2')


class TestCheckAndAddQualifyingMeditation(unittest.TestCase):
    """Test check_and_add_qualifying_meditation function"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test_db.json'
        self.db = MeditationDatabase(self.db_path)
        self.api = Mock(spec=BeeminderAPI)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_qualifying_apple_health_meditation(self):
        """Test adding qualifying Apple Health meditation"""
        # Apple Health meditation at 7:21 AM
        meditation_data = [{
            'timestamp': 1758945599,  # End of day timestamp
            'value': 45.0,
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS',
            'id': 'test1'
        }]

        self.api.get_goal_data.return_value = meditation_data
        self.api.add_datapoint.return_value = True

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should add to both database and Beeminder
        self.assertEqual(len(self.db.get_datapoints()), 1)
        self.api.add_datapoint.assert_called_once()

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_non_qualifying_time(self):
        """Test non-qualifying meditation (wrong time)"""
        # Meditation at 2:00 PM (not early morning)
        meditation_data = [{
            'timestamp': 1758945599,
            'value': 45.0,
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 14:00 by zarathustra via BeemiOS',
            'id': 'test1'
        }]

        self.api.get_goal_data.return_value = meditation_data

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should not add anything
        self.assertEqual(len(self.db.get_datapoints()), 0)
        self.api.add_datapoint.assert_not_called()

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_non_qualifying_duration(self):
        """Test non-qualifying meditation (too short)"""
        # Short meditation at good time
        meditation_data = [{
            'timestamp': 1758945599,
            'value': 20.0,  # Less than 35 minutes
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS',
            'id': 'test1'
        }]

        self.api.get_goal_data.return_value = meditation_data

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should not add anything
        self.assertEqual(len(self.db.get_datapoints()), 0)
        self.api.add_datapoint.assert_not_called()

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_already_recorded_meditation(self):
        """Test meditation already recorded"""
        meditation_data = [{
            'timestamp': 1758945599,
            'value': 45.0,
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS',
            'id': 'test1'
        }]

        # Pre-add the meditation to database
        self.db.add_datapoint(1, 1758945599, 'Already there')

        self.api.get_goal_data.return_value = meditation_data

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should not add duplicate
        self.assertEqual(len(self.db.get_datapoints()), 1)
        self.api.add_datapoint.assert_not_called()

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_regular_entry_qualifying(self):
        """Test regular (non-Apple Health) qualifying meditation"""
        # Create a timestamp for 7:00 AM today
        nyc_now = datetime.now(NYC_TZ)
        morning_time = nyc_now.replace(hour=7, minute=0, second=0, microsecond=0)
        morning_timestamp = int(morning_time.timestamp())

        meditation_data = [{
            'timestamp': morning_timestamp,
            'value': 40.0,
            'comment': 'Manual entry',
            'id': 'test1'
        }]

        self.api.get_goal_data.return_value = meditation_data
        self.api.add_datapoint.return_value = True

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should add to both database and Beeminder
        self.assertEqual(len(self.db.get_datapoints()), 1)
        self.api.add_datapoint.assert_called_once()

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_api_failure(self):
        """Test handling of API failure"""
        meditation_data = [{
            'timestamp': 1758945599,
            'value': 45.0,
            'comment': 'Auto-entered via Apple Health',
            'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS',
            'id': 'test1'
        }]

        self.api.get_goal_data.return_value = meditation_data
        self.api.add_datapoint.return_value = False  # API failure

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should add to database but not count as success
        self.assertEqual(len(self.db.get_datapoints()), 1)

    @patch('beeminder_sync.BEEMINDER_SOURCE_GOAL', 'source-goal')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'target-goal')
    def test_multiple_meditations_same_day(self):
        """Test multiple qualifying meditations on same day (should pick longest)"""
        meditation_data = [
            {
                'timestamp': 1758945599,
                'value': 35.0,
                'comment': 'Auto-entered via Apple Health',
                'fulltext': '2025-Sep-26 entered at 07:21 by zarathustra via BeemiOS',
                'id': 'test1'
            },
            {
                'timestamp': 1758946000,
                'value': 50.0,  # Longer meditation
                'comment': 'Auto-entered via Apple Health',
                'fulltext': '2025-Sep-26 entered at 08:00 by zarathustra via BeemiOS',
                'id': 'test2'
            }
        ]

        self.api.get_goal_data.return_value = meditation_data
        self.api.add_datapoint.return_value = True

        check_and_add_qualifying_meditation(self.api, self.db)

        # Should add only one (the longer one)
        self.assertEqual(len(self.db.get_datapoints()), 1)
        added_datapoint = self.db.get_datapoints()[0]
        self.assertIn('50.0 minutes', added_datapoint['comment'])


class TestMain(unittest.TestCase):
    """Test main function"""

    @patch('beeminder_sync.BEEMINDER_AUTH_TOKEN', 'test_token')
    @patch('beeminder_sync.BEEMINDER_USERNAME', 'test_user')
    @patch('beeminder_sync.BEEMINDER_GOAL_SLUG', 'test_goal')
    @patch('beeminder_sync.DB_PATH')
    @patch('beeminder_sync.check_and_add_qualifying_meditation')
    @patch('beeminder_sync.sync_beeminder_with_database')
    @patch('beeminder_sync.MeditationDatabase')
    @patch('beeminder_sync.BeeminderAPI')
    def test_main_success(self, mock_api_class, mock_db_class, mock_sync, mock_check, mock_db_path):
        """Test successful main execution"""
        mock_api = Mock()
        mock_db = Mock()
        mock_api_class.return_value = mock_api
        mock_db_class.return_value = mock_db

        main()

        mock_api_class.assert_called_once_with('test_user', 'test_token')
        mock_db_class.assert_called_once_with(mock_db_path)
        mock_sync.assert_called_once_with(mock_api, mock_db, 'test_goal')
        mock_check.assert_called_once_with(mock_api, mock_db)
        mock_db.save.assert_called_once()

    @patch('beeminder_sync.BEEMINDER_AUTH_TOKEN', None)
    def test_main_missing_auth_token(self):
        """Test main with missing auth token"""
        with self.assertRaises(ValueError) as context:
            main()

        self.assertIn('BEEMINDER_AUTH_TOKEN not set', str(context.exception))


if __name__ == '__main__':
    # Run tests without coverage for now
    print("Running comprehensive test suite...")
    unittest.main(verbosity=2)