from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from .contract_register import contract_register
from .models import Contract
from .pjn_contracts import store_contract
from .seed import today
from .test_contract_insights import raw


class ContractRegisterTests(TestCase):
    def setUp(self):
        store_contract(raw(1))
        store_contract(raw(2, naziv='Tiskanje obrazcev', narociloNaziv='Tiskanje obrazcev', vrednost=None,
            sifCpv='79800000 - Tiskarske storitve', objavaDejanskaDatum='2024-03-01T00:00:00',
            trajanjeDo=(today()-timedelta(days=1)).isoformat(),
            narocnik=[{'naziv': 'Drugo mesto', 'maticna': '0000001000'}],
            izvajalec=[{'naziv': 'Tiskarna', 'maticna': '0000002000'}]))
        store_contract(raw(3, vrednost=0, trajanjeDo=None, objavaDejanskaDatum=None,
                           sifCpv='72000000 - IT storitve'))
        store_contract(raw(99, tip='Dodatek', sifObrazecOznaka='DOD', idPogodbaPrej=1,
                           trajanjeDo=(today()+timedelta(days=500)).isoformat()))

    def ids(self, **params):
        return [x['id'] for x in contract_register(params)['results']]

    def test_register_uses_saved_contracts_without_ai_or_portal_calls(self):
        with patch('tenders.pjn_contracts.fetch_json', side_effect=AssertionError('Portal call')), \
                patch('tenders.ai.structured_call', side_effect=AssertionError('AI call')):
            response = self.client.get('/api/contracts')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 3)
        self.assertNotIn(99, [x['id'] for x in data['results']])
        self.assertEqual(data['dataset']['contracts'], 3)
        self.assertEqual(data['dataset']['addenda'], 1)

    def test_search_terms_combine_buyer_contractor_and_subject(self):
        self.assertEqual(self.ids(q='Primer Klima'), [1, 3])
        self.assertEqual(self.ids(q='Tiskarna obrazcev'), [2])
        self.assertEqual(self.ids(q='neobstojeca'), [])

    def test_filters_apply_effective_end_including_addenda(self):
        self.assertEqual(self.ids(status='ended'), [2])
        self.assertEqual(self.ids(status='unknown'), [3])
        self.assertEqual(self.ids(status='active'), [1])
        self.assertEqual(self.ids(status='expiring'), [])
        self.assertEqual(self.ids(year='2024'), [2])
        self.assertEqual(self.ids(cpv='72'), [3])

    def test_value_sort_keeps_zero_and_puts_unknown_last(self):
        self.assertEqual(self.ids(sort='value'), [1, 3, 2])
        self.assertEqual(self.ids(sort='ending'), [2, 1, 3])

    def test_pagination_is_stable_and_does_not_serialize_entire_register(self):
        Contract.objects.bulk_create([Contract(id=i, data={'title': f'Pogodba {i}'}) for i in range(100, 125)])
        first = contract_register({})
        second = contract_register({'page': '2'})
        self.assertEqual(first['count'], 28)
        self.assertEqual(len(first['results']), 20)
        self.assertEqual(len(second['results']), 8)
        self.assertFalse({x['id'] for x in first['results']} & {x['id'] for x in second['results']})

    def test_invalid_filters_are_rejected(self):
        for params in ({'page': '0'}, {'sort': 'sql'}, {'cpv': 'abc'}, {'year': '99999'},
                       {'status': 'arbitrary'}, {'q': ' '.join(['beseda']*9)}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get('/api/contracts', params).status_code, 400)
