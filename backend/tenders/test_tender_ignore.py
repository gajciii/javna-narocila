from django.test import TestCase
from rest_framework.test import APIClient

from .filtering import apply_filters
from .models import TenderIgnore
from .seed import ensure_seed
from .services import all_tenders


class TenderIgnoreTests(TestCase):
    """Ignored tenders leave every list and stay reachable in their own view."""

    def setUp(self):
        ensure_seed()
        self.client = APIClient()

    def ids(self, view):
        return {t['id'] for t in self.client.get('/api/tenders', {'view': view}).data['results']}

    def test_ignored_tender_is_hidden_from_lists_until_restored(self):
        self.assertIn('energy-iot', self.ids('all'))
        response = self.client.post('/api/tenders/energy-iot/ignore', {'ignored': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ignored'])
        for view in ('all', 'recommended', 'following'):
            self.assertNotIn('energy-iot', self.ids(view))
        self.assertEqual(self.ids('ignored'), {'energy-iot'})
        self.assertTrue(self.client.get('/api/tenders/energy-iot').data['ignored'])
        self.client.post('/api/tenders/energy-iot/ignore', {'ignored': False}, format='json')
        self.assertIn('energy-iot', self.ids('all'))
        self.assertEqual(self.ids('ignored'), set())

    def test_ignoring_stops_following_and_following_restores(self):
        self.client.post('/api/tenders/satellite/follow', {'following': True}, format='json')
        detail = self.client.post('/api/tenders/satellite/ignore', {'ignored': True}, format='json').data
        self.assertFalse(detail['following'])
        detail = self.client.post('/api/tenders/satellite/follow', {'following': True}, format='json').data
        self.assertTrue(detail['following'])
        self.assertFalse(detail['ignored'])
        self.assertFalse(TenderIgnore.objects.exists())

    def test_invalid_value_and_filters_without_flag(self):
        self.assertEqual(self.client.post('/api/tenders/energy-iot/ignore', {'ignored': 'da'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/tenders/missing/ignore', {'ignored': True}, format='json').status_code, 404)
        tender = {'id': 'x', 'title': 'Šola', 'buyer': 'Občina', 'match': {'score': 50}, 'following': False}
        self.assertEqual(apply_filters([tender], {'view': 'all'}), [tender])
        self.assertTrue(all('ignored' in t for t in all_tenders()))

    def test_detail_reports_keywords_of_the_search_that_opened_it(self):
        detail = self.client.get('/api/tenders/energy-iot', {'q': 'IoT, podmornica'}).data
        self.assertEqual([item['term'] for item in detail['keyword_matches']], ['IoT'])
        self.assertNotIn('keyword_matches', self.client.get('/api/tenders/energy-iot').data)
        self.assertEqual(self.client.get('/api/tenders/energy-iot', {'q': 'x' * 2001}).status_code, 400)
