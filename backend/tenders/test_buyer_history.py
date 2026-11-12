from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from .buyer_history import history
from .models import PastAward, Tender


class BuyerHistoryTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='buyer-history-test', data={
            'source_type': 'real', 'buyer': 'Občina Primer', 'source_metadata': {
                'buyers': [{'name': 'Občina Primer', 'registration_number': '1234567'}]}})

    def award(self, pk, name='Dobavitelj A', reg='7654321', **changes):
        data = {'buyer': 'Občina Primer', 'buyer_registration_number': '1234567000',
                'title': f'Posel {pk}', 'lot_title': '', 'notice_number': f'JN{pk:06d}/2026-SL4/01',
                'winners': [{'name': name, 'registration_number': reg}], 'awarded': True,
                'awarded_value': 100, 'currency': 'EUR', 'tenders_received': 2,
                'framework': False, 'cpv': ['72262000']}
        data.update(changes)
        return PastAward.objects.create(id=f'award-{pk}', notice_id=str(pk), dossier_id=str(pk),
            published_on=date(2026, 10, 1), data=data)

    def test_count_share_and_value_have_explicit_denominators(self):
        self.award(1, tenders_received=1)
        self.award(2, reg='7654321000', awarded_value=200, tenders_received=None)
        self.award(3, name='Dobavitelj B', reg='7654322', awarded_value=300)
        self.award(4, awarded=False, winners=[])
        result = history(self.tender, {})
        s = result['summary']
        self.assertEqual((s['lots'], s['awarded_lots'], s['not_awarded_lots']), (4, 3, 1))
        self.assertEqual((s['single_bid_lots'], s['known_bid_lots'], s['single_bid_share']), (1, 2, .5))
        a = result['suppliers'][0]
        self.assertEqual((a['wins'], a['value_eur'], a['value_share']), (2, 300, .5))
        self.assertAlmostEqual(a['share'], 2 / 3)
        self.assertNotIn('similarity', result['results'][0])
        self.assertTrue(result['results'][0]['notice_url'].startswith('https://www.enarocanje.si/'))

    def test_joint_framework_missing_currency_and_value_do_not_inflate_money(self):
        joint = [{'name': 'Dobavitelj A', 'registration_number': '7654321'},
                 {'name': 'Dobavitelj B', 'registration_number': '7654322'}]
        self.award(1, winners=joint, awarded_value=1000)
        self.award(2, framework=True, awarded_value=2000)
        self.award(3, currency='USD', awarded_value=3000)
        self.award(4, awarded_value=None)
        self.award(5, currency=None)
        self.award(6, awarded_value=0)
        result = history(self.tender, {})
        s = result['summary']
        self.assertEqual((s['total_value_eur'], s['value_lots'], s['excluded_value_lots']), (0, 1, 5))
        self.assertEqual((s['joint_lots'], s['framework_lots']), (1, 1))
        self.assertEqual(result['suppliers'][0]['wins'], 6)
        self.assertIsNone(result['suppliers'][0]['value_share'])
        self.assertEqual(result['suppliers'][1]['joint_wins'], 1)

    def test_duplicate_winner_aliases_count_once(self):
        self.award(1, winners=[{'name': 'A', 'registration_number': '7654321'},
                              {'name': 'A d.o.o.', 'registration_number': '7654321000'}])
        result = history(self.tender, {})
        self.assertEqual(len(result['suppliers']), 1)
        self.assertEqual(result['suppliers'][0]['wins'], 1)
        self.assertEqual(result['summary']['value_lots'], 1)

    def test_latest_lot_notice_replaces_older_one_even_across_date_filter(self):
        old = self.award(1, title='Tiskanje', lot_title='Sklop A')
        new = self.award(2, title='Tiskanje', lot_title='Sklop A', awarded_value=500)
        new.dossier_id = old.dossier_id
        new.data['previous_notice_id'] = old.notice_id
        new.published_on = date(2026, 11, 1)
        new.save()
        result = history(self.tender, {})
        self.assertEqual(result['summary']['superseded_lots'], 1)
        self.assertEqual(result['summary']['total_value_eur'], 500)
        self.assertEqual(history(self.tender, {'to': '2026-10-31'})['summary']['lots'], 0)

    def test_repeated_awards_without_correction_link_are_not_discarded(self):
        a = self.award(1, title='Material', lot_title='Material')
        b = self.award(2, title='Material', lot_title='Material')
        b.dossier_id = a.dossier_id
        b.save()
        self.assertEqual(history(self.tender, {})['summary']['lots'], 2)

    def test_same_named_lots_within_one_notice_are_preserved(self):
        a = self.award(1, title='Material', lot_title='Material')
        b = self.award(2, title='Material', lot_title='Material')
        b.dossier_id, b.notice_id = a.dossier_id, a.notice_id
        b.save()
        self.assertEqual(history(self.tender, {})['summary']['lots'], 2)

    def test_buyer_registration_prevents_merging_different_buyers(self):
        self.award(1)
        self.award(2, buyer_registration_number='9999999000')
        self.award(3, buyer='Novo ime občine')
        result = history(self.tender, {})
        self.assertEqual(result['summary']['lots'], 2)
        self.assertEqual(result['buyer']['matched_by'], 'registration_number')

    def test_old_tenders_resolve_unambiguous_buyer_but_reject_ambiguous_names(self):
        self.tender.data.pop('source_metadata')
        self.award(1)
        self.assertEqual(history(self.tender, {})['buyer']['registration_number'], '1234567000')
        self.award(2, buyer_registration_number='9999999000')
        result = history(self.tender, {})
        self.assertEqual(result['mode'], 'ambiguous')
        self.assertIsNone(result['summary'])

    def test_name_only_matching_and_explicit_multi_buyer_selection(self):
        self.tender.data['source_metadata']['buyers'].append({'name': 'Drug naročnik', 'registration_number': ''})
        self.award(1, buyer='Drug naročnik', buyer_registration_number='')
        result = history(self.tender, {'buyer': '1'})
        self.assertEqual(result['summary']['lots'], 1)
        self.assertEqual(result['buyer']['matched_by'], 'name')
        self.assertEqual(history(self.tender, {})['summary']['lots'], 0)

    def test_date_cpv_and_unknown_dates(self):
        self.award(1)
        self.award(2, cpv=['45000000'])
        unknown = self.award(3)
        unknown.published_on = None
        unknown.save()
        result = history(self.tender, {'from': '2026-10-01', 'to': '2026-10-31', 'cpv': '72'})
        self.assertEqual(result['summary']['lots'], 1)
        self.assertEqual(history(self.tender, {})['summary']['undated_lots'], 1)

    def test_supplier_drilldown_keeps_summary_denominator(self):
        self.award(1)
        self.award(2, name='B', reg='1111111')
        result = history(self.tender, {'supplier': 'id:1111111000'})
        self.assertEqual(result['history_count'], 1)
        self.assertEqual(result['summary']['awarded_lots'], 2)
        self.assertEqual(result['results'][0]['id'], 'award-2')

    def test_pagination(self):
        for i in range(1, 24):
            self.award(i)
        result = history(self.tender, {'page': '2'})
        self.assertEqual(result['history_count'], 23)
        self.assertEqual(len(result['results']), 3)
        self.assertEqual(result['summary']['awarded_lots'], 23)

    def test_signals_require_sufficient_sample_and_known_bids(self):
        for i in range(1, 10):
            self.award(i, tenders_received=1)
        self.assertEqual([s['kind'] for s in history(self.tender, {})['signals']], ['sample'])
        self.award(10, tenders_received=1)
        self.assertEqual([s['kind'] for s in history(self.tender, {})['signals']], ['concentration', 'competition'])
        for row in PastAward.objects.all():
            row.data['tenders_received'] = None
            row.save()
        result = history(self.tender, {})
        self.assertIsNone(result['summary']['single_bid_share'])
        self.assertEqual([s['kind'] for s in result['signals']], ['concentration'])

    @patch('tenders.views.ensure_seed', side_effect=AssertionError('Must not seed'))
    def test_endpoint_validation_and_empty_dataset(self, seed):
        client = APIClient()
        self.award(1)
        self.assertEqual(client.get(f'/api/tenders/{self.tender.pk}/buyer-history').status_code, 200)
        for params in [{'from': 'invalid'}, {'from': '2026-11-01', 'to': '2026-10-01'},
                       {'cpv': '72 OR 1=1'}, {'page': '-1'}, {'page': '0'}, {'buyer': '99'}]:
            response = client.get(f'/api/tenders/{self.tender.pk}/buyer-history', params)
            self.assertEqual(response.status_code, 400, params)
        self.tender.data['source_type'] = 'demo'
        self.assertEqual(history(self.tender, {})['mode'], 'empty')
