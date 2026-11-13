from datetime import date, datetime, timedelta, timezone as tz
from unittest.mock import patch

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from .contract_insights import expected_tenders, incumbents
from .models import Contract, ContractSyncState, Tender
from .pjn_contracts import (normalize_contract, registration_id, store_contract, sync_buyer_contracts,
                            sync_contract_list)
from .seed import today

FILE = 'https://www.enarocanje.si/api/datoteka/get?id=abc'


def raw(pk, **changes):
    """Shape of a public pogodbaGet response (2026-11-13), reduced to the fields we read."""
    base = {'id': pk, 'tip': 'Pogodba', 'sifObrazecOznaka': 'POG', 'idPogodbaPrej': None, 'idDosje': 900 + pk,
            'idSifCpv': None, 'sifCpv': '45331000 - Instaliranje ogrevalnih, prezračevalnih in klimatskih naprav',
            'naziv': f'Pogodba {pk}', 'narociloNaziv': 'Vzdrževanje klimatskih naprav', 'sifNarociloVrsta': 'Gradnje',
            'sifPogodbaTip': 'Pogodbe o izvedbi javnega naročila', 'vrednost': 1000.0,
            'datumSklenitve': '2025-01-10T00:00:00', 'trajanjeOd': '2025-01-10T00:00:00',
            'trajanjeDo': (today() + timedelta(days=60)).isoformat() + 'T00:00:00',
            'objavaDejanskaDatum': '2025-01-15T10:00:00', 'objavaIdent': f'JN00{pk}/2025-POG/01',
            'dosjeObjavaIdent': f'JN00{pk}/2025',
            'narocnik': [{'naziv': 'Občina Primer', 'maticna': '1234567000'}],
            'izvajalec': [{'naziv': 'Klima d.o.o.', 'maticna': '7654321'}],
            'datoteka': [{'ime': 'Pogodba.pdf', 'url': FILE}], 'dodatek': None}
    base.update(changes)
    return base


class NormalizeTests(TestCase):
    def test_contract_fields_and_registration_numbers(self):
        item = normalize_contract(raw(1))
        self.assertEqual((item['cpv'], item['buyer_registration'], item['is_addendum']), ('45331000', '1234567000', False))
        self.assertEqual(item['data']['contractors'], [{'name': 'Klima d.o.o.', 'registration_number': '7654321000'}])
        self.assertEqual(item['data']['files'][0]['url'], FILE)
        self.assertEqual(registration_id('12345'), '')
        with self.assertRaises(ValueError):
            normalize_contract({'id': '1'})

    def test_untrusted_file_links_are_dropped(self):
        item = normalize_contract(raw(1, datoteka=[{'ime': 'x.pdf', 'url': 'https://example.com/x.pdf'}]))
        self.assertEqual(item['data']['files'], [])

    def test_addendum_extends_contract_from_either_side(self):
        end = today() + timedelta(days=30)
        store_contract(raw(1, trajanjeDo=end.isoformat() + 'T00:00:00'))
        later = end + timedelta(days=200)
        store_contract(raw(2, tip='Dodatek', sifObrazecOznaka='DOD', idPogodbaPrej=1, vrednost=0.0,
                           trajanjeDo=later.isoformat() + 'T00:00:00'))
        contract = Contract.objects.get(pk=1)
        self.assertEqual((contract.effective_end, contract.addenda_count), (later, 1))
        self.assertIsNone(Contract.objects.get(pk=2).effective_end)
        # The contract's own list of addenda counts even when the addendum itself was never fetched.
        store_contract(raw(1, trajanjeDo=end.isoformat() + 'T00:00:00', dodatek=[
            {'id': 3, 'tip': 'Dodatek', 'trajanjeDo': (later + timedelta(days=1)).isoformat() + 'T00:00:00'}]))
        contract.refresh_from_db()
        self.assertEqual((contract.effective_end, contract.addenda_count), (later + timedelta(days=1), 2))


class SyncTests(TestCase):
    def grid(self, rows):
        return {'data': rows, 'lastRow': len(rows)}

    @patch('tenders.pjn_contracts.sleep')
    @patch('tenders.pjn_contracts.fetch_json')
    def test_list_sync_skips_known_fetches_missing_parent_and_moves_watermark(self, fetch, _):
        store_contract(raw(1))
        details = {2: raw(2, tip='Dodatek', idPogodbaPrej=5), 5: raw(5)}

        def answer(path, body=None, **_):
            if body is not None:
                return self.grid([{'id': 1}, {'id': 2}])
            return details[int(path.rsplit('=', 1)[1])]
        fetch.side_effect = answer
        result = sync_contract_list(until=date(2026, 11, 12))
        self.assertEqual((result['listed'], result['fetched'], result['errors']), (2, 1, []))
        self.assertTrue(Contract.objects.filter(pk=5, addenda_count=1).exists())
        self.assertEqual(ContractSyncState.objects.get(pk='list').synced_until, date(2026, 11, 12))

    @patch('tenders.pjn_contracts.sleep')
    @patch('tenders.pjn_contracts.fetch_json', side_effect=lambda path, body=None, **_: {'data': [], 'lastRow': 0})
    def test_backfill_never_moves_the_daily_watermark_across_a_gap(self, fetch, _):
        sync_contract_list(date(2024, 1, 1), date(2024, 12, 31))
        self.assertIsNone(ContractSyncState.objects.get(pk='list').synced_until)
        sync_contract_list(until=date(2026, 11, 12))
        sync_contract_list(date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(ContractSyncState.objects.get(pk='list').synced_until, date(2026, 11, 12))
        sync_contract_list(date(2026, 11, 10), date(2026, 11, 13))
        self.assertEqual(ContractSyncState.objects.get(pk='list').synced_until, date(2026, 11, 13))

    @patch('tenders.pjn_contracts.sleep')
    @patch('tenders.pjn_contracts.fetch_json')
    def test_failed_contract_keeps_watermark(self, fetch, _):
        fetch.side_effect = lambda path, body=None, **_: self.grid([{'id': 7}]) if body else {'id': 99}
        result = sync_contract_list(date(2026, 11, 1), date(2026, 11, 12))
        self.assertEqual(len(result['errors']), 1)
        self.assertIsNone(ContractSyncState.objects.get(pk='list').synced_until)

    @patch('tenders.pjn_contracts.sleep')
    @patch('tenders.pjn_contracts.fetch_json')
    def test_parallel_backfill_stores_every_contract_and_parent(self, fetch, _):
        rows = [{'id': i} for i in range(1, 31)]
        details = {i: raw(i) for i in range(1, 31)}
        details[30] = raw(30, tip='Dodatek', idPogodbaPrej=500)
        details[500] = raw(500)
        fetch.side_effect = lambda path, body=None, **_: self.grid(rows) if body else details[int(path.rsplit('=', 1)[1])]
        result = sync_contract_list(date(2026, 11, 1), date(2026, 11, 12), workers=4, rate=50)
        self.assertEqual((result['fetched'], result['parents'], result['errors']), (30, 1, []))
        self.assertEqual(Contract.objects.count(), 31)
        self.assertEqual(Contract.objects.get(pk=500).addenda_count, 1)
        with self.assertRaises(ValueError):
            sync_contract_list(date(2026, 11, 1), date(2026, 11, 12), workers=0)

    @patch('tenders.pjn_contracts.sleep')
    @patch('tenders.pjn_contracts.fetch_json')
    def test_buyer_sync_fetches_only_related_cpv_and_then_rests(self, fetch, _):
        from .pjn_normalize import codelists
        ids = {v['code']: int(k) for k, v in codelists()['cpv'].items()}
        rows = [{'id': 1, 'idSifCpv': ids['45331000']}, {'id': 2, 'idSifCpv': ids['72000000']}]
        fetched = []

        def answer(path, body=None, **_):
            if body is not None:
                self.assertEqual(body['narocnikMaticna'], '1234567000')
                return self.grid(rows)
            fetched.append(path)
            return raw(1)
        fetch.side_effect = answer
        result = sync_buyer_contracts('1234567', ['45330000'])
        self.assertEqual((result['matched'], result['fetched']), (1, 1))
        self.assertEqual(len(fetched), 1)
        self.assertEqual(sync_buyer_contracts('1234567', ['45330000'])['mode'], 'fresh')


class InsightTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='incumbent-test', data={
            'source_type': 'real', 'cpv': ['45331000'], 'title': 'Vzdrževanje klim',
            'source_metadata': {'dossier_id': 555, 'buyers': [{'name': 'Občina Primer', 'registration_number': '1234567'}]}})

    def test_active_related_contract_is_the_incumbent(self):
        store_contract(raw(1, trajanjeDo=(today() - timedelta(days=10)).isoformat() + 'T00:00:00',
                           izvajalec=[{'naziv': 'Stari izvajalec', 'maticna': '1111111'}]))
        store_contract(raw(2))
        store_contract(raw(3, sifCpv='72000000 - Storitve IT'))  # unrelated subject
        store_contract(raw(4, idDosje=555))  # the tender's own contract
        store_contract(raw(5, narocnik=[{'naziv': 'Drug naročnik', 'maticna': '9999999000'}]))
        result = incumbents(self.tender)
        self.assertEqual(result['headline']['kind'], 'active')
        self.assertEqual([p['name'] for p in result['headline']['contractors']], ['Klima d.o.o.'])
        self.assertEqual([r['id'] for r in result['results']], [2, 1])
        self.assertEqual(result['results'][1]['status'], 'ended')
        self.assertFalse(result['complete'])

    def test_without_registration_number_nothing_is_linked_by_name(self):
        self.tender.data['source_metadata']['buyers'] = [{'name': 'Občina Primer', 'registration_number': ''}]
        store_contract(raw(2))
        self.assertEqual(incumbents(self.tender)['results'], [])

    def test_expected_tenders_match_profile_terms_within_window(self):
        store_contract(raw(1))
        store_contract(raw(2, trajanjeDo=(today() + timedelta(days=500)).isoformat() + 'T00:00:00'))
        store_contract(raw(3, narociloNaziv='Čiščenje prostorov', naziv='Pogodba za čiščenje',
                           sifCpv='90910000 - Storitve čiščenja'))
        store_contract(raw(4, trajanjeDo=None))
        profile = {'keywords': ['klimatske naprave'], 'expertise': []}
        result = expected_tenders(profile, {'months': '12'})
        self.assertEqual([r['id'] for r in result['results']], [1])
        self.assertEqual(result['results'][0]['matched_terms'], ['klimatske naprave'])
        self.assertEqual(expected_tenders(profile, {'months': '24'})['count'], 2)
        self.assertEqual(expected_tenders({'keywords': []}, {})['mode'], 'profile_missing')
        self.assertEqual(expected_tenders({'keywords': []}, {'cpv': '9091'})['count'], 1)
        with self.assertRaises(ValidationError):
            expected_tenders(profile, {'months': '5'})

    def test_newer_related_contract_is_flagged(self):
        store_contract(raw(1))
        store_contract(raw(2, objavaDejanskaDatum='2026-06-01T10:00:00', trajanjeDo='2028-01-01T00:00:00'))
        result = expected_tenders({'keywords': ['klimatske naprave']}, {'months': '3'})
        self.assertEqual(result['results'][0]['newer_contract']['id'], 2)

    def test_views(self):
        store_contract(raw(2))
        from rest_framework.test import APIClient
        client = APIClient()
        response = client.get(f'/api/tenders/{self.tender.pk}/incumbents')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['id'], 2)
        with patch('tenders.pjn_contracts.sync_buyer_contracts', return_value={'mode': 'fresh', 'fetched': 0, 'remaining': 0, 'errors': []}) as sync:
            self.assertTrue(client.post(f'/api/tenders/{self.tender.pk}/incumbents').json()['refresh']['skipped'])
            sync.assert_called_once()
        self.assertEqual(client.get('/api/expected-tenders?months=7').status_code, 400)
        self.assertEqual(client.get('/api/expected-tenders?months=12').status_code, 200)
