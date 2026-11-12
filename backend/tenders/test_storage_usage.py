import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from . import storage_usage


class StorageUsageTests(SimpleTestCase):
    def setUp(self):
        cache.delete_many([storage_usage.SNAPSHOT_KEY, storage_usage.LOCK_KEY])
        self.addCleanup(cache.delete_many, [storage_usage.SNAPSHOT_KEY, storage_usage.LOCK_KEY])

    def test_first_request_starts_one_measurement_without_blocking(self):
        with patch.object(storage_usage, 'start_refresh') as start:
            first, second = storage_usage.current(), storage_usage.current()
        self.assertEqual(start.call_count, 1)
        self.assertTrue(first['measuring'])
        self.assertIsNone(second['database'])

    def test_snapshot_is_reused_for_an_hour(self):
        measured_at = timezone.now() - timedelta(minutes=59)
        cache.set(storage_usage.SNAPSHOT_KEY, {'measured_at': measured_at, 'database': {'bytes': 10},
                                               'storage': {'bytes': 20, 'objects': 1}}, None)
        with patch.object(storage_usage, 'start_refresh') as start:
            usage = storage_usage.current()
        start.assert_not_called()
        self.assertFalse(usage['measuring'])
        self.assertEqual(usage['database'], {'bytes': 10})
        self.assertEqual(usage['next_refresh_at'], measured_at + timedelta(hours=1))

    def test_stale_snapshot_is_shown_while_remeasuring(self):
        cache.set(storage_usage.SNAPSHOT_KEY, {'measured_at': timezone.now() - timedelta(hours=1, seconds=1),
                                               'database': {'bytes': 10}, 'storage': {'bytes': 20}}, None)
        with patch.object(storage_usage, 'start_refresh') as start:
            usage = storage_usage.current()
        start.assert_called_once()
        self.assertTrue(usage['measuring'])
        self.assertEqual(usage['storage'], {'bytes': 20})

    def test_refresh_stores_snapshot_and_releases_lock(self):
        cache.add(storage_usage.LOCK_KEY, True)
        with patch.object(storage_usage, 'database_size', return_value={'bytes': 5}), \
                patch.object(storage_usage, 'object_storage_size', side_effect=RuntimeError('down')), \
                patch.object(storage_usage.connection, 'close'):
            storage_usage.refresh()
        snapshot = cache.get(storage_usage.SNAPSHOT_KEY)
        self.assertEqual(snapshot['database'], {'bytes': 5})
        self.assertIn('error', snapshot['storage'])
        self.assertIsNone(cache.get(storage_usage.LOCK_KEY))

    def test_local_document_storage_is_summed(self):
        with tempfile.TemporaryDirectory() as directory:
            indexed = Path(directory) / 'indexed' / 'ab'
            indexed.mkdir(parents=True)
            (indexed / 'one').write_bytes(b'x' * 3)
            (indexed / 'two').write_bytes(b'x' * 4)
            with override_settings(PIPELINE_S3_ENDPOINT='', MEDIA_ROOT=Path(directory)):
                self.assertEqual(storage_usage.object_storage_size(),
                                 {'bytes': 7, 'objects': 2, 'location': 'Lokalni disk'})

    @override_settings(PIPELINE_S3_ENDPOINT='http://storage:9000', PIPELINE_S3_BUCKET='docs')
    def test_bucket_listing_is_summed_across_pages(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {'Contents': [{'Size': 100}, {'Size': 50}]}, {'Contents': [{'Size': 7}]}, {}]
        with patch.object(storage_usage.pipeline_storage, 'client', return_value=client):
            self.assertEqual(storage_usage.object_storage_size(), {'bytes': 157, 'objects': 3, 'location': 'S3 · docs'})
        client.get_paginator.return_value.paginate.assert_called_once_with(Bucket='docs')
