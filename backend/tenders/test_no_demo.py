from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import CompanyProfile, DemoEvent, Document, Notification, Partner, Tender
from .seed import demo_profile, seed_tenders


@override_settings(TEST_FIXTURE_DATA=False, ACCOUNT_REQUIRE_LOGIN=True)
class RealWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='workspace-owner', is_staff=True)
        self.client = APIClient()
        self.client.force_login(self.user)

    def test_new_workspace_has_no_invented_company_capabilities_or_notices(self):
        response = self.client.get('/api/bootstrap')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['meta']['demo'])
        self.assertNotEqual(data['meta']['ai_mode'], 'demo')
        self.assertEqual(data['profile']['name'], '')
        self.assertEqual(data['profile']['source'], 'user')
        for field in ('references', 'certifications', 'technologies', 'keywords'):
            self.assertEqual(data['profile'][field], [])
        self.assertNotIn('tenders', data)
        self.assertEqual(self.client.get('/api/tenders?view=all').json()['results'], [])
        self.assertEqual(data['notifications'], [])
        self.assertEqual(Tender.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DemoEvent.objects.count(), 0)

    def test_existing_demo_company_is_hidden_without_deleting_it(self):
        original = demo_profile()
        record = CompanyProfile.objects.create(owner=self.user, data=original, is_active=True)
        data = self.client.get('/api/bootstrap').json()
        self.assertNotEqual(data['profile']['id'], record.pk)
        self.assertNotIn(record.pk, [p['id'] for p in data['profiles']])
        record.refresh_from_db()
        self.assertEqual(record.data, original)

    def test_real_company_and_legacy_profile_without_source_are_preserved(self):
        original = {'name': 'Podjetje iz registra', 'registration_number': '1234567000',
                    'references': [], 'certifications': ['ISO 9001'], 'technologies': []}
        record = CompanyProfile.objects.create(owner=self.user, data=original, is_active=True)
        data = self.client.get('/api/profile').json()
        self.assertEqual(data['id'], record.pk)
        record.refresh_from_db()
        self.assertEqual(record.data, original)

    def test_legacy_fake_notices_notifications_and_partners_are_not_exposed(self):
        fake = Tender.objects.create(id='legacy-fake', data=seed_tenders()[0])
        real = {**seed_tenders()[0], 'id': 'real-notice', 'source_type': 'real'}
        Tender.objects.create(id=real['id'], data=real)
        Notification.objects.create(event_key='old-demo', tender=fake, type='new', title='Demo', is_demo=True)
        Document.objects.create(id='legacy-fake-doc', tender=fake, title='fake.pdf', path='/missing')
        from .accounts import account_scope
        from .improvements import company_key
        self.client.get('/api/profile')
        with account_scope(self.user.pk):
            key = company_key()
        partner = Partner.objects.create(company_key=key, source_type='demo', data=demo_profile())
        result = self.client.get('/api/bootstrap').json()
        listed = self.client.get('/api/tenders?view=all').json()['results']
        self.assertEqual([t['id'] for t in listed], ['real-notice'])
        self.assertEqual(result['notifications'], [])
        self.assertEqual(self.client.get('/api/partners').json(), [])
        for path in ('/api/tenders/legacy-fake', '/api/documents/legacy-fake-doc', f'/api/partners/{partner.pk}'):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_demo_actions_cannot_reset_or_populate_the_workspace(self):
        for path in ('/api/demo/event', '/api/demo/reset'):
            self.assertEqual(self.client.post(path, {'type': 'new'}, format='json').status_code, 410)
        self.assertEqual(self.client.post('/api/profile/prefill', {'provider': 'demo'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/partners', {'source_type': 'demo', 'profile': demo_profile()}, format='json').status_code, 400)
        self.assertEqual(Tender.objects.count(), 0)
        self.assertEqual(DemoEvent.objects.count(), 0)

    def test_new_actual_company_starts_without_fixture_references(self):
        response = self.client.post('/api/profiles', {'name': 'Dejansko podjetje', 'registration_number': '7654321000'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['references'], [])
        self.assertEqual(response.json()['certifications'], [])
        self.assertEqual(response.json()['technologies'], [])

    def test_rule_based_filters_use_real_runtime_label(self):
        from .ai import suggest_filters
        self.assertEqual(suggest_filters('Iščemo spletne aplikacije')['mode'], 'rules')
