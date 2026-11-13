from django.test import TestCase
from rest_framework.test import APIClient

from .models import CompanyProfile
from .seed import ensure_seed, get_profile
from .improvements import company_key


class MultipleCompaniesTests(TestCase):
    def setUp(self):
        ensure_seed()
        self.client = APIClient()
        self.original = get_profile()

    def test_create_switch_and_edit_preserve_both_profiles(self):
        response = self.client.post('/api/profiles', {'name': 'Drugo podjetje', 'registration_number': '1234567'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        second = response.data
        self.assertNotEqual(second['id'], self.original['id'])
        self.assertEqual(second['references'], [])
        self.assertEqual(second['technologies'], [])
        self.assertIsNone(second['staff_count'])
        self.assertNotEqual(company_key(second), company_key(self.original))
        response = self.client.put('/api/profile', {**second, 'capacity': 'Nova ekipa'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post('/api/profiles/1/activate').status_code, 200)
        self.assertEqual(get_profile(), self.original)
        response = self.client.post(f"/api/profiles/{second['id']}/activate")
        self.assertEqual(response.data['capacity'], 'Nova ekipa')
        self.assertEqual(CompanyProfile.objects.filter(is_active=True).count(), 1)
        bootstrap = self.client.get('/api/bootstrap').data
        self.assertEqual(len(bootstrap['profiles']), 2)
        self.assertEqual(bootstrap['profile']['id'], second['id'])

    def test_invalid_create_and_unknown_switch_leave_active_profile_unchanged(self):
        self.assertEqual(self.client.post('/api/profiles', {'name': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/profiles/999/activate').status_code, 404)
        self.assertEqual(CompanyProfile.objects.count(), 1)
        self.assertEqual(get_profile(), self.original)

    def test_duplicate_registration_and_stale_updates_are_rejected(self):
        second = self.client.post('/api/profiles', {'name': 'Drugo', 'registration_number': '1234567'}, format='json').data
        duplicate = self.client.post('/api/profiles', {'name': 'Podvojeno', 'registration_number': '1234567000'}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        stale = self.client.put('/api/profile', self.original, format='json')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(get_profile()['id'], second['id'])
        self.client.post('/api/profiles/1/activate')
        duplicate_edit = self.client.put('/api/profile', {**self.original, 'registration_number': '1234567000'}, format='json')
        self.assertEqual(duplicate_edit.status_code, 400)
        self.assertEqual(get_profile(), self.original)
