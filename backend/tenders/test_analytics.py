from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from tenders import analytics


class AnalyticsTests(SimpleTestCase):
    def setUp(self):
        analytics._client = None
        self.addCleanup(setattr, analytics, '_client', None)

    @patch.dict('os.environ', {'POSTHOG_KEY': ''})
    def test_without_key_nothing_is_sent(self):
        with patch('posthog.Posthog') as posthog:
            analytics.capture('keyword_expansion', suggestions=2)
        posthog.assert_not_called()

    @patch.dict('os.environ', {'POSTHOG_KEY': 'phc_test', 'POSTHOG_HOST': ''})
    def test_events_are_anonymous_and_go_to_eu_cloud(self):
        with patch('posthog.Posthog') as posthog, patch('tenders.analytics.atexit.register'):
            analytics.capture('similar_awards', mode='ai')
        posthog.assert_called_once_with('phc_test', host='https://eu.i.posthog.com', disable_geoip=True)
        kwargs = posthog.return_value.capture.call_args.kwargs
        self.assertEqual(kwargs['distinct_id'], 'razpizi-server')
        self.assertEqual(kwargs['properties'], {'mode': 'ai', '$process_person_profile': False})

    @patch.dict('os.environ', {'POSTHOG_KEY': 'phc_test'})
    def test_client_failure_never_raises(self):
        analytics._client = MagicMock(capture=MagicMock(side_effect=RuntimeError('network')))
        analytics.capture('pipeline_job_finished')
