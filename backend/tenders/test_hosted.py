from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, Client, override_settings

from radar.deployment import public_origin
from .models import Tender


class PublicURLTests(SimpleTestCase):
    def test_origin_is_normalized_for_hosts_and_csrf(self):
        self.assertEqual(public_origin('https://APP.example.test:443/'), ('https://app.example.test', 'app.example.test'))
        self.assertEqual(public_origin('https://app.example.test:8443'), ('https://app.example.test:8443', 'app.example.test'))
        self.assertEqual(public_origin(''), ('', None))

    def test_path_credentials_and_malformed_origins_are_rejected(self):
        for value in ('https://user:private@app.example.test', 'https://app.example.test/path',
                      'https://app.example.test?key=secret', 'https://app.example.test/#hash',
                      'file:///tmp/file', 'https://', 'https://app.example.test:invalid', 'https://bad host'):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                public_origin(value)


@override_settings(HOSTED_REQUIRE_LOGIN=True, PUBLIC_APP_URL='https://app.example.test',
    ALLOWED_HOSTS=['app.example.test', 'testserver', 'localhost'],
    CSRF_TRUSTED_ORIGINS=['https://app.example.test'], SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'), SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class HostedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('web-admin', password='test-only-password', is_staff=True)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST='app.example.test', HTTP_X_FORWARDED_PROTO='https')

    def login(self):
        csrf = self.client.get('/api/admin/pipeline/session').json()['csrf_token']
        response = self.client.post('/api/admin/pipeline/login',
            {'username': 'web-admin', 'password': 'test-only-password'}, content_type='application/json',
            HTTP_ORIGIN='https://app.example.test', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies['sessionid']['secure'])
        self.assertTrue(response.cookies['csrftoken']['secure'])
        return response.json()['csrf_token']

    def test_anonymous_api_access_requires_login_without_seeding(self):
        for path in ('/api/bootstrap', '/api/profile', '/api/documents/missing'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['code'], 'login_required')
        self.assertEqual(self.client.post('/api/demo/reset', {}, content_type='application/json').status_code, 401)
        self.assertFalse(Tender.objects.exists())

    def test_https_login_and_allowed_origin_work_behind_proxy(self):
        csrf = self.login()
        response = self.client.post('/api/admin/pipeline/schedule', {'enabled': False},
            content_type='application/json', HTTP_ORIGIN='https://app.example.test', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)

    def test_all_hosted_mutations_require_csrf_and_exact_origin(self):
        csrf = self.login()
        url = '/api/filters/suggest'
        with patch('tenders.views.suggest_filters', return_value={'filters': {}}) as suggest:
            self.assertEqual(self.client.post(url, {'message': 'test'}, content_type='application/json',
                HTTP_ORIGIN='https://app.example.test').status_code, 403)
            self.assertEqual(self.client.post(url, {'message': 'test'}, content_type='application/json',
                HTTP_ORIGIN='https://app.example.test.evil.test', HTTP_X_CSRFTOKEN=csrf).status_code, 403)
            self.assertEqual(self.client.post(url, {'message': 'test'}, content_type='application/json',
                HTTP_ORIGIN='http://app.example.test', HTTP_X_CSRFTOKEN=csrf).status_code, 403)
            suggest.assert_not_called()
            self.assertEqual(self.client.post(url, {'message': 'test'}, content_type='application/json',
                HTTP_ORIGIN='https://app.example.test', HTTP_X_CSRFTOKEN=csrf).status_code, 200)

    def test_internal_http_healthcheck_does_not_redirect_or_call_ai(self):
        internal = Client(HTTP_HOST='localhost')
        with patch('tenders.relevance.requests.post', side_effect=AssertionError('Health must not call AI')):
            response = internal.get('/api/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok'})
        self.assertFalse(Tender.objects.exists())

    def test_health_returns_generic_unavailable_when_database_fails(self):
        with patch('tenders.health.connection.cursor', side_effect=DatabaseError('private connection detail')):
            response = self.client.get('/api/health')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private connection', response.content.decode())

    def test_unproxied_public_http_redirects_to_https(self):
        response = Client(HTTP_HOST='app.example.test').get('/api/admin/pipeline/session')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], 'https://app.example.test/api/admin/pipeline/session')
