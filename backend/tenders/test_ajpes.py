import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase
from django.utils import timezone

from .ajpes import RESOURCE_ID, RegistryUnavailable, lookup, normalize_company, preview, request_json
from .models import CompanyLookupCache
from .seed import ensure_seed, get_profile

ROW = json.loads((Path(__file__).parent / 'fixtures/ajpes-company.json').read_text(encoding='utf-8'))


class AjpesTests(TestCase):
    def setUp(self):
        ensure_seed()
        self.network = self.enterContext(patch('tenders.ajpes.request_json', side_effect=self.source))

    def source(self, action, params):
        if action == 'package_show':
            return {'name': 'poslovni-register-slovenije', 'metadata_modified': '2026-11-01T00:00:29',
                    'resources': [{'id': RESOURCE_ID}]}
        return {'records': [deepcopy(ROW)], 'total': 1}

    def test_live_search_uses_official_dataset_and_labels_provenance(self):
        response = self.client.get('/api/companies/search', {'q': 'GIC GRADNJE'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['mode'], 'live')
        self.assertEqual(data['results'][0]['registration_number'], '5851513000')
        self.assertEqual(data['results'][0]['address'], 'Prvomajska ulica 15B, 3250 Rogaška Slatina')
        self.assertEqual(data['source']['license'], 'CC BY 4.0')
        self.assertEqual(self.network.call_args_list[0].args[1]['resource_id'], RESOURCE_ID)
        self.assertNotIn('activity', data['results'][0])

    def test_seven_digit_registration_uses_exact_filter_not_fuzzy_search(self):
        result = lookup('5851513')
        params = self.network.call_args_list[0].args[1]
        self.assertEqual(json.loads(params['filters']), {'Matična številka': '5851513000'})
        self.assertNotIn('q', params)
        self.assertEqual(len(result['results']), 1)

    def test_registration_keeps_leading_zeros_and_house_suffix(self):
        row = {**ROW, 'Matična številka': '0123456000'}
        data = normalize_company(row)
        self.assertEqual(data['registration_number'], '0123456000')
        self.assertIn('15B', data['address'])

    def test_branch_is_distinct_and_not_selected_automatically(self):
        branch = {**ROW, 'Matična številka': '5851513001', 'Pravnoorganizacijska oblika': 'Poslovna enota'}
        self.network.side_effect = lambda action, params: {'records': [branch, ROW], 'total': 2} if action == 'datastore_search' else self.source(action, params)
        result = lookup('GIC')
        self.assertEqual([c['registration_number'] for c in result['results']], ['5851513000', '5851513001'])
        self.assertEqual(get_profile()['registration_number'], 'DEMO-001')

    def test_real_preview_has_no_demo_capabilities_and_does_not_save(self):
        before = get_profile()
        response = self.client.post('/api/profile/prefill', {'registration_number': '5851513000'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        profile = response.json()['profile']
        for field in ['references', 'technologies', 'keywords', 'expertise', 'certifications']:
            self.assertEqual(profile[field], [])
        self.assertIsNone(profile['staff_count'])
        self.assertEqual(profile['activity'], '')
        self.assertEqual(profile['website'], '')
        self.assertEqual(get_profile(), before)

    def test_profile_save_preserves_verified_source_not_client_claims(self):
        profile = preview('5851513000')['profile']
        profile['registry_source']['url'] = 'https://untrusted.example'
        profile['registry_source']['name'] = 'Invented company'
        profile['activity'] = 'Razvoj programske opreme'
        response = self.client.put('/api/profile', profile, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertEqual(saved['registry_source']['name'], ROW['Popolno ime'])
        self.assertEqual(saved['registry_source']['url'], 'https://podatki.gov.si/dataset/poslovni-register-slovenije')
        self.assertEqual(saved['activity'], profile['activity'])
        reloaded = self.client.get('/api/profile').json()
        self.assertEqual(reloaded['registry_source'], saved['registry_source'])
        self.assertEqual(reloaded['references'], [])

    def test_fabricated_registry_source_cannot_be_saved(self):
        profile = {**get_profile(), 'registration_number': '5851513000',
                   'registry_source': {'provider': 'ajpes', 'registration_number': '5851513000'}}
        response = self.client.put('/api/profile', profile, content_type='application/json')
        self.assertNotIn('registry_source', response.json())

    def test_changing_company_number_clears_old_provenance(self):
        profile = preview('5851513000')['profile']
        self.client.put('/api/profile', profile, content_type='application/json')
        response = self.client.put('/api/profile', {'registration_number': '1234567000'}, content_type='application/json')
        self.assertNotIn('registry_source', response.json())

    def test_cache_avoids_repeat_requests(self):
        original = lookup('GIC')
        self.network.reset_mock()
        cached = lookup('gic')
        self.assertEqual(cached['mode'], 'cached')
        self.assertEqual(cached['source']['retrieved_at'], original['source']['retrieved_at'])
        self.network.assert_not_called()

    def test_outage_uses_labeled_stale_cache_with_original_dataset_date(self):
        original = lookup('GIC')
        CompanyLookupCache.objects.exclude(pk='metadata').update(fetched_at=timezone.now() - timedelta(days=2))
        CompanyLookupCache.objects.filter(pk='metadata').update(payload={'dataset_updated_at': '2099-01-01'})
        self.network.side_effect = RegistryUnavailable('Offline')
        result = lookup('GIC')
        self.assertEqual(result['mode'], 'cached')
        self.assertTrue(result['stale'])
        self.assertIn('starejši', result['warning'])
        self.assertEqual(result['source']['dataset_updated_at'], original['source']['dataset_updated_at'])

    def test_outage_without_cache_returns_503_not_demo_company(self):
        self.network.side_effect = RegistryUnavailable('Offline')
        response = self.client.get('/api/companies/search', {'q': 'Podjetje'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'ajpes_unavailable')
        self.assertNotIn('profile', response.json())

    def test_no_result_is_empty_and_exact_preview_is_404(self):
        self.network.side_effect = lambda action, params: {'records': [], 'total': 0} if action == 'datastore_search' else self.source(action, params)
        self.assertEqual(lookup('Neobstoječe')['results'], [])
        response = self.client.post('/api/profile/prefill', {'registration_number': '1234567000'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('profile', response.json())

    def test_wrong_record_is_not_cached_as_selected_company(self):
        with self.assertRaises(RegistryUnavailable):
            preview('1234567000')
        self.assertFalse(CompanyLookupCache.objects.filter(pk='company:1234567000').exists())

    def test_invalid_query_and_registration_fail_before_network(self):
        for query in ['', 'x', '12345678', 'x' * 161]:
            response = self.client.get('/api/companies/search', {'q': query})
            self.assertEqual(response.status_code, 400)
        self.network.assert_not_called()


class AjpesTransportTests(TestCase):
    @patch('tenders.ajpes.requests.get')
    def test_successful_wire_response_and_fixed_destination(self, get):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_content.return_value = [json.dumps({'success': True, 'result': {'records': [ROW], 'total': 1}}).encode()]
        get.return_value = response
        result = request_json('datastore_search', {'q': 'Podjetje'})
        self.assertEqual(result['records'][0], ROW)
        self.assertEqual(get.call_args.args[0], 'https://podatki.gov.si/api/3/action/datastore_search')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    @patch('tenders.ajpes.requests.get')
    def test_redirects_and_oversized_responses_are_rejected(self, get):
        response = MagicMock(status_code=302)
        response.__enter__.return_value = response
        get.return_value = response
        with self.assertRaises(RegistryUnavailable):
            request_json('datastore_search', {})
        response.status_code = 200
        response.iter_content.return_value = [b'x' * (1024 * 1024 + 1)]
        with self.assertRaises(RegistryUnavailable):
            request_json('datastore_search', {})

    @patch('tenders.ajpes.requests.get', side_effect=requests.Timeout)
    def test_timeout_does_not_expose_request_details(self, get):
        with self.assertRaisesMessage(RegistryUnavailable, 'OPSI trenutno ni dosegljiv'):
            request_json('datastore_search', {})
