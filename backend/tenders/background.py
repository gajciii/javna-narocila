"""Run slow, idempotent follow-up work outside the request.

One thread per key at a time. A request for a key that is already running marks it
dirty, so the work runs once more afterwards with fresh data instead of being lost.
"""
import logging
import threading

from django.conf import settings
from django.db import connections

log = logging.getLogger(__name__)
_lock = threading.Lock()
_running = {}  # key -> rerun requested while running


def run_once(key, fn):
    if settings.BACKGROUND_TASKS_INLINE:
        fn()
        return
    with _lock:
        if key in _running:
            _running[key] = True
            return
        _running[key] = False

    def target():
        try:
            while True:
                try:
                    fn()
                except Exception:
                    log.exception('Background task %s failed', key)
                with _lock:
                    if not _running[key]:
                        del _running[key]
                        return
                    _running[key] = False
        finally:
            connections.close_all()

    threading.Thread(target=target, daemon=True, name=f'background:{key}').start()


def is_running(key):
    with _lock:
        return key in _running
