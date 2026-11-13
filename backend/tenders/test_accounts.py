import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .accounts import account_scope
from .email_notifications import enqueue
from .improvements import company_key
from .models import (CompanyProfile, SavedSearch, Tender, TenderFollow, Notification,
                     NotificationEmail, EmailNotificationSettings, Partner, ImprovementPlan, EspdDraft)
from .seed import ensure_seed, get_profile

PASSWORD = 'Razpis!DobraLuna82'


@override_settings(ACCOUNT_REQUIRE_LOGIN=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   PIPELINE_S3_ENDPOINT='', PUBLIC_APP_URL='https://razpisi.example.com', EMAIL_HOST='smtp.example.com',
                   DEFAULT_FROM_EMAIL='razpisi@example.com', EMAIL_PROVIDER='smtp', EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
class AccountTests(TestCase):
    def setUp(self):
        cache.clear()
        ensure_seed()
        self.a = get_user_model().objects.create_user('ana@example.com', email='ana@example.com', password=PASSWORD)
        self.b = get_user_model().objects.create_user('bor@example.com', email='bor@example.com', password=PASSWORD)
        self.ca = Client(enforce_csrf_checks=True)
        self.cb = Client(enforce_csrf_checks=True)
        self.ca.force_login(self.a)
        self.cb.force_login(self.b)
        self.guest = Client(enforce_csrf_checks=True)

    def write(self, client, path, data=None, method='post'):
        token = client.get('/api/auth/session').json()['csrf_token']
        return getattr(client, method)(path, json.dumps(data or {}), content_type='application/json', HTTP_X_CSRFTOKEN=token)

    def profile(self, client):
        return client.get('/api/profile').json()

    def test_guests_cannot_access_application_data(self):
        for path in ('/api/bootstrap', '/api/profile', '/api/searches', '/api/notifications', '/api/tenders'):
            response = self.guest.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['code'], 'login_required')
        self.assertEqual(self.guest.get('/api/auth/session').status_code, 200)

    def test_registration_normalizes_email_hashes_password_and_creates_session(self):
        response = self.write(self.guest, '/api/auth/register', {'email': 'Nova@Example.com', 'password': PASSWORD, 'password_confirm': PASSWORD, 'is_staff': True})
        self.assertEqual(response.status_code, 201, response.content)
        user = get_user_model().objects.get(username='nova@example.com')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertFalse(user.is_staff)
        self.assertTrue(self.guest.get('/api/auth/session').json()['authenticated'])
        self.assertTrue(CompanyProfile.objects.filter(owner__isnull=True).exists())
        self.assertEqual(self.profile(self.guest)['owner_id'], user.pk)

    def test_registration_rejects_weak_mismatched_duplicate_and_malformed_input(self):
        for data in ({'email': 'x@example.com', 'password': '12345678', 'password_confirm': '12345678'},
                     {'email': 'x@example.com', 'password': PASSWORD, 'password_confirm': 'different'},
                     {'email': 'ANA@example.com', 'password': PASSWORD, 'password_confirm': PASSWORD},
                     {'email': [], 'password': PASSWORD}, []):
            self.assertEqual(self.write(self.guest, '/api/auth/register', data).status_code, 400)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_login_logout_and_inactive_account(self):
        self.assertEqual(self.write(self.guest, '/api/auth/login', {'username': 'ANA@example.com', 'password': 'wrong'}).status_code, 403)
        result = self.write(self.guest, '/api/auth/login', {'username': 'ANA@example.com', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['authenticated'])
        self.assertEqual(self.write(self.guest, '/api/auth/logout').status_code, 200)
        self.assertEqual(self.guest.get('/api/profile').status_code, 401)
        self.a.is_active = False
        self.a.save()
        self.assertEqual(self.write(self.guest, '/api/auth/login', {'username': self.a.username, 'password': PASSWORD}).status_code, 403)

    def test_csrf_is_required_for_login_registration_logout_and_app_writes(self):
        for client, path in ((self.guest, '/api/auth/login'), (self.guest, '/api/auth/register'),
                             (self.ca, '/api/auth/logout'), (self.ca, '/api/profiles')):
            response = client.post(path, '{}', content_type='application/json')
            self.assertEqual(response.status_code, 403)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.write(self.guest, '/api/auth/login', {'username': 'bad', 'password': 'bad'}).status_code, 403)
        self.assertEqual(self.write(self.guest, '/api/auth/login', {'username': self.a.username, 'password': PASSWORD}).status_code, 429)

    def test_profiles_and_active_selection_are_private_even_for_the_same_company(self):
        pa, pb = self.profile(self.ca), self.profile(self.cb)
        self.assertNotEqual(pa['id'], pb['id'])
        data = {'name': 'Isto podjetje', 'registration_number': '1234567'}
        ra = self.write(self.ca, '/api/profiles', data)
        rb = self.write(self.cb, '/api/profiles', data)
        self.assertEqual(ra.status_code, 201, ra.content)
        self.assertEqual(rb.status_code, 201, rb.content)
        self.assertEqual(self.write(self.cb, f"/api/profiles/{ra.json()['id']}/activate").status_code, 404)
        self.assertEqual(self.write(self.ca, f"/api/profiles/{pa['id']}/activate").status_code, 200)
        self.assertEqual(self.profile(self.cb)['id'], rb.json()['id'])
        self.assertEqual(len(self.ca.get('/api/bootstrap').json()['profiles']), 2)
        self.assertNotIn(rb.json()['id'], [p['id'] for p in self.ca.get('/api/bootstrap').json()['profiles']])
        stale = self.write(self.cb, '/api/profile', ra.json(), method='put')
        self.assertEqual(stale.status_code, 409)

    def test_searches_and_following_are_private(self):
        search = self.write(self.ca, '/api/searches', {'name': 'Zasebno', 'filters': {}}).json()
        self.assertEqual(self.cb.get('/api/searches').json(), [])
        self.assertEqual(self.write(self.cb, f"/api/searches/{search['id']}", method='delete').status_code, 404)
        self.assertEqual(self.write(self.ca, '/api/tenders/energy-iot/follow', {'following': True}).status_code, 200)
        self.assertTrue(self.ca.get('/api/tenders/energy-iot').json()['following'])
        self.assertFalse(self.cb.get('/api/tenders/energy-iot').json()['following'])

    def test_company_related_private_data_uses_account_namespace(self):
        pa, pb = self.profile(self.ca), self.profile(self.cb)
        ka, kb = company_key(pa), company_key(pb)
        self.assertNotEqual(ka, kb)
        partner = Partner.objects.create(company_key=ka, source_type='demo', data={'name': 'Zasebni partner'})
        plan = ImprovementPlan.objects.create(company_key=ka, source_type='demo', name='Zasebni načrt', actions=[])
        EspdDraft.objects.create(company_key=ka, tender_id='energy-iot', answers={'operator': {'email': 'zasebno@example.com'}})
        self.assertEqual(self.cb.get(f'/api/partners/{partner.pk}').status_code, 404)
        self.assertEqual(self.cb.get(f'/api/improvement-plans/{plan.pk}').status_code, 404)
        espd = self.cb.get('/api/tenders/energy-iot/espd')
        self.assertEqual(espd.status_code, 200)
        self.assertNotIn('zasebno@example.com', espd.content.decode())

    def test_notification_read_state_and_email_preferences_are_private(self):
        notice = Notification.objects.create(tender_id='energy-iot', event_key='public-test', type='deadline', title='Rok', body='Sprememba')
        self.assertEqual(self.write(self.ca, '/api/notifications/read', {'id': notice.pk}).status_code, 200)
        a = next(n for n in self.ca.get('/api/notifications').json() if n['id'] == notice.pk)
        b = next(n for n in self.cb.get('/api/notifications').json() if n['id'] == notice.pk)
        self.assertTrue(a['read'])
        self.assertFalse(b['read'])
        self.assertEqual(self.write(self.ca, '/api/notifications/email-settings', {'enabled': True, 'email': self.a.email}, method='put').status_code, 200)
        self.assertEqual(self.cb.get('/api/notifications/email-settings').json()['email'], '')

    def test_email_outbox_supports_multiple_recipients_without_cross_cancellation(self):
        tender = Tender.objects.create(pk='account-real', data={'source_type': 'real', 'title': 'Javni razpis'})
        for user in (self.a, self.b):
            TenderFollow.objects.create(owner=user, tender=tender)
            EmailNotificationSettings.objects.create(owner=user, enabled=True, email=user.email, enabled_since=timezone.now() - timedelta(minutes=1))
        Notification.objects.create(tender=tender, event_key='real-change', type='deadline', title='Rok', body='Javno', is_demo=False)
        self.assertEqual(enqueue(), 2)
        self.assertEqual(self.write(self.ca, '/api/notifications/email-settings', {'enabled': False, 'email': self.a.email}, method='put').status_code, 200)
        self.assertEqual(NotificationEmail.objects.get(owner=self.a).state, 'cancelled')
        self.assertEqual(NotificationEmail.objects.get(owner=self.b).state, 'pending')

    def test_source_changes_are_notified_when_only_an_account_follows(self):
        from pathlib import Path
        from .pjn_normalize import normalize_notice
        from .pjn_sync import persist_notice
        raw = json.loads((Path(__file__).parent / 'fixtures/pjn-notice.json').read_text())
        raw.update(id=9999999, idDosje=999999, razpisnaDokumentacijaURL=None)
        data = normalize_notice(raw, '9999999')
        tender, _, _ = persist_notice(data)
        self.assertFalse(tender.following)
        TenderFollow.objects.create(owner=self.a, tender=tender)
        data['summary'] = 'Posodobljen javni opis predmeta naročila.'
        persist_notice(data)
        self.assertTrue(Notification.objects.filter(tender=tender, type='correction', is_demo=False).exists())

    def test_portable_export_excludes_account_profiles_and_private_drafts(self):
        import gzip
        from .database_export import database_archive
        profile = self.profile(self.ca)
        EspdDraft.objects.create(company_key=company_key(profile), tender_id='energy-iot', answers={'private': 'secret-draft'})
        with database_archive() as archive:
            records = json.loads(gzip.decompress(archive.read()))
        self.assertFalse(any(row['model'] == 'tenders.companyprofile' and row['pk'] == profile['id'] for row in records))
        self.assertNotIn('secret-draft', json.dumps(records))

    def test_members_cannot_run_global_admin_mutations(self):
        for path in ('/api/demo/reset', '/api/demo/event', '/api/import', '/api/sources/pjn/sync', '/api/admin/pipeline/jobs'):
            self.assertEqual(self.write(self.ca, path).status_code, 403)

    def test_staff_can_claim_legacy_profiles_but_members_cannot(self):
        legacy = CompanyProfile.objects.get(owner__isnull=True)
        key = company_key({**legacy.data, 'owner_id': None})
        plan = ImprovementPlan.objects.create(company_key=key, name='Stari načrt', source_type='demo')
        self.write(self.guest, '/api/auth/login', {'username': self.a.username, 'password': PASSWORD})
        legacy.refresh_from_db()
        self.assertIsNone(legacy.owner_id)
        staff = get_user_model().objects.create_user('admin', password=PASSWORD, is_staff=True)
        self.assertEqual(self.write(self.guest, '/api/auth/login', {'username': 'admin', 'password': PASSWORD}).status_code, 200)
        legacy.refresh_from_db()
        self.assertEqual(legacy.owner_id, staff.pk)
        plan.refresh_from_db()
        self.assertEqual(plan.company_key, company_key({**legacy.data, 'owner_id': staff.pk}))
