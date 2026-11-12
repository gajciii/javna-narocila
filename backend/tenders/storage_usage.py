"""Database and document storage size for the admin overview, measured at most once per hour.

The admin overview is polled every few seconds, while listing a large bucket takes a while, so the
measurement runs in a background thread and requests only read the last cached snapshot.
"""
import logging
import threading
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from . import pipeline_storage

logger = logging.getLogger(__name__)
SNAPSHOT_KEY = 'admin:storage-usage'
LOCK_KEY = 'admin:storage-usage:measuring'
REFRESH_INTERVAL = timedelta(hours=1)
LOCK_SECONDS = 15 * 60


def database_size():
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_database_size(current_database())')
            return {'bytes': cursor.fetchone()[0]}
    path = Path(settings.DATABASES['default']['NAME'])
    files = [path, path.with_name(f'{path.name}-wal')]
    return {'bytes': sum(file.stat().st_size for file in files if file.is_file())}


def object_storage_size():
    if not settings.PIPELINE_S3_ENDPOINT:
        root = Path(settings.MEDIA_ROOT) / 'indexed'
        files = [file for file in root.rglob('*') if file.is_file()] if root.is_dir() else []
        return {'bytes': sum(file.stat().st_size for file in files), 'objects': len(files), 'location': 'Lokalni disk'}
    size = count = 0
    pages = pipeline_storage.client().get_paginator('list_objects_v2').paginate(Bucket=settings.PIPELINE_S3_BUCKET)
    for page in pages:
        for item in page.get('Contents', ()):
            size += item['Size']
            count += 1
    return {'bytes': size, 'objects': count, 'location': f'S3 · {settings.PIPELINE_S3_BUCKET}'}


def measure():
    snapshot = {'measured_at': timezone.now()}
    for name, measure_part in (('database', database_size), ('storage', object_storage_size)):
        try:
            snapshot[name] = measure_part()
        except Exception:
            logger.exception('Measuring %s size failed', name)
            snapshot[name] = {'error': 'Velikosti ni bilo mogoče izmeriti.'}
    return snapshot


def refresh():
    try:
        cache.set(SNAPSHOT_KEY, measure(), None)
    finally:
        cache.delete(LOCK_KEY)
        connection.close()


def start_refresh():
    threading.Thread(target=refresh, name='storage-usage', daemon=True).start()


def current():
    """Last snapshot; starts a background measurement when it is missing or older than an hour."""
    snapshot = cache.get(SNAPSHOT_KEY)
    stale = snapshot is None or timezone.now() - snapshot['measured_at'] >= REFRESH_INTERVAL
    if stale and cache.add(LOCK_KEY, True, LOCK_SECONDS):
        try:
            start_refresh()
        except Exception:
            cache.delete(LOCK_KEY)
            raise
    if snapshot is None:
        return {'measuring': True, 'measured_at': None, 'next_refresh_at': None, 'database': None, 'storage': None}
    return {**snapshot, 'measuring': stale, 'next_refresh_at': snapshot['measured_at'] + REFRESH_INTERVAL}
