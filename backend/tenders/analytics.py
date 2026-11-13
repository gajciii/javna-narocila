"""Server-side product analytics (PostHog). Without POSTHOG_KEY every call is a no-op.

Events describe what the system did (pipeline jobs, search features), not who did it: they use
one anonymous server identity, create no person profiles and carry no personal data.
"""
import atexit
import logging
import os

log = logging.getLogger(__name__)
DISTINCT_ID = 'razpizi-server'
_client = None


def client():
    global _client
    key = os.environ.get('POSTHOG_KEY')
    if not key:
        return None
    if _client is None:
        from posthog import Posthog
        _client = Posthog(key, host=os.environ.get('POSTHOG_HOST') or 'https://eu.i.posthog.com', disable_geoip=True)
        # Events are sent in the background in batches; flush them when the process exits.
        atexit.register(_client.shutdown)
    return _client


def capture(event, **properties):
    """Never raises: analytics must not affect the request or job that reports it."""
    try:
        posthog = client()
        if posthog is not None:
            posthog.capture(event, distinct_id=DISTINCT_ID, properties={**properties, '$process_person_profile': False})
    except Exception as exc:
        log.warning('Analytics event %s not sent: %s', event, type(exc).__name__)
