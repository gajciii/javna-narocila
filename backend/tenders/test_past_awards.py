"""Similar past awards; no network or real API key is used."""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from .models import PastAward, SimilarAwardsCache, Tender
from .past_awards import import_notices, normalize_notice, similar_awards, summarize


def notice(notice_id=1, title='Tiskarske storitve', cpv='79800000 - Tiskarske storitve', dossier=10, number='JN000001/2026-SL4/01',
           awards=None, lots=None):
    return {
        'id': notice_id, 'dossierId': dossier, 'noticeNumber': number, 'title': title, 'buyer': 'Občina Primer',
        'buyerRegistrationNumber': '1234567000', 'publicationDate': '2026-10-01', 'contractType': 'SERVICES', 'mainCpv': cpv,
        'shortDescription': 'Tisk brošur in plakatov.', 'procedureTypeName': 'Odprti postopek', 'currency': 'EUR',
        'lots': lots or [{'lotId': 1, 'title': title, 'description': 'Tisk brošur in plakatov.', 'cpv': [cpv], 'estimatedValue': 10000}],
        'awards': awards or [{'lotId': 1, 'status': 'selec-w', 'tendersReceived': 3, 'lowestAdmissibleOffer': 8000,
                              'highestAdmissibleOffer': 9200, 'awardedValue': 8000, 'currency': 'EUR',
                              'winners': [{'name': 'Tiskarna d.o.o.', 'registrationNumber': '7654321000'}]}],
    }


def real_tender(pk='pjn-dosje-99', title='Tiskarske storitve za občino', number='JN000099/2026-SL1/01', dossier=99):
    return Tender.objects.create(pk=pk, data={
        'title': title, 'buyer': 'Občina Drugje', 'kind': 'services', 'cpv': ['79800000'], 'source_type': 'real',
        'description': 'Tisk brošur, plakatov in letakov.', 'lots': [],
        'source_metadata': {'notice_number': number, 'dossier_id': dossier}})


class NormalizeTests(TestCase):
    def test_award_fields_are_typed_and_bounded(self):
        raw = notice()
        raw['awards'][0]['tendersReceived'] = True  # bool is not a count
        raw['awards'][0]['winners'].append({'name': 'Brez MŠ', 'registrationNumber': 'x<script>'})
        row = normalize_notice(raw)[0]
        self.assertEqual(row['id'], 'pjn-1-1')
        self.assertEqual(row['data']['cpv'], ['79800000'])
        self.assertEqual(row['data']['kind'], 'services')
        self.assertIsNone(row['data']['tenders_received'])
        self.assertEqual(row['data']['winners'][1], {'name': 'Brez MŠ', 'registration_number': ''})
        self.assertTrue(row['data']['awarded'])

    def test_unawarded_lot_and_invalid_record(self):
        raw = notice(awards=[{'lotId': 1, 'status': 'clos-nw', 'tendersReceived': 0, 'winners': None}])
        self.assertFalse(normalize_notice(raw)[0]['data']['awarded'])
        self.assertEqual(normalize_notice({'id': 'x'}), [])
        self.assertEqual(normalize_notice('not a dict'), [])

    def test_reimport_updates_instead_of_duplicating(self):
        self.assertEqual(import_notices([notice()])['created'], 1)
        result = import_notices([notice(title='Tiskarske storitve 2')])
        self.assertEqual((result['created'], result['updated']), (0, 1))
        self.assertEqual(PastAward.objects.get().data['title'], 'Tiskarske storitve 2')


class SummaryTests(TestCase):
    def test_framework_and_foreign_currency_are_left_out_of_price_ratios(self):
        base = {'awarded': True, 'framework': False, 'currency': 'EUR', 'estimated_value': 100, 'awarded_value': 90,
                'lowest_offer': 90, 'highest_offer': 99, 'tenders_received': 2, 'winners': [{'name': 'A', 'registration_number': '1'}]}
        rows = [base, {**base, 'framework': True, 'awarded_value': 5}, {**base, 'currency': 'USD', 'awarded_value': 500},
                {**base, 'awarded': False, 'winners': [], 'tenders_received': 1}]
        s = summarize(rows)
        self.assertEqual((s['median_price_to_estimate'], s['price_to_estimate_count']), (0.9, 1))
        self.assertEqual(s['single_bid_share'], 0.25)
        self.assertEqual(s['top_winners'][0]['wins'], 3)
        self.assertEqual(s['not_awarded'], 1)


@patch.dict('os.environ', {'GEMINI_API_KEY': ''})
class SimilarTextTests(TestCase):
    def setUp(self):
        import_notices([notice(1), notice(2, title='Gradnja pločnika', cpv='45233161 - Gradnja pločnikov', dossier=20,
                                         number='JN000002/2026-SL4/01'),
                        notice(3, title='Tiskarske storitve', dossier=99, number='JN000099/2026-EUe29/01')])

    def test_text_mode_finds_similar_and_skips_own_procedure(self):
        result = similar_awards(real_tender())
        self.assertEqual(result['mode'], 'text')
        self.assertEqual([r['notice_id'] for r in result['results']], ['1'])
        self.assertEqual(result['results'][0]['notice_url'], 'https://www.enarocanje.si/#/pregled-objav/1')
        self.assertEqual(result['summary']['top_winners'][0]['registration_number'], '7654321000')
        self.assertEqual(result['dataset']['license'], 'CC BY 4.0')

    def test_own_procedure_is_skipped_by_procedure_number_without_dossier(self):
        tender = real_tender(dossier=None, number='JN000001/2026-EUe16/01')
        self.assertNotIn('1', [r['notice_id'] for r in similar_awards(tender)['results']])

    def test_demo_tender_is_not_compared_with_real_awards(self):
        tender = Tender.objects.create(pk='demo-print', data={'title': 'Tiskarske storitve', 'source_type': 'demo', 'cpv': ['79800000']})
        result = similar_awards(tender)
        self.assertEqual((result['mode'], result['results']), ('empty', []))
        self.assertIn('demo', result['message'])


@patch.dict('os.environ', {'GEMINI_API_KEY': 'test-never-sent', 'GEMINI_DECISION_MODEL': ''})
class SimilarAiTests(TestCase):
    def setUp(self):
        import_notices([notice(1), notice(4, title='Tisk letakov', dossier=40, number='JN000004/2026-SL4/01')])

    @patch('tenders.past_awards.requests.post')
    def test_gemini_ranks_filters_and_result_is_cached(self, post):
        def answer(*args, **kwargs):
            questions = kwargs['json']['questions']
            self.assertTrue(all(qid.startswith('q') for qid in questions))
            return MagicMock(status_code=200, json=lambda: {'answers': {'q0': {'noul': 0.9}, 'q1': {'noul': 0.2}, 'q99': {'noul': 1.0}}})
        post.side_effect = answer
        tender = real_tender()
        first = similar_awards(tender)
        self.assertEqual(first['mode'], 'ai')
        self.assertEqual(len(first['results']), 1)
        self.assertEqual(first['results'][0]['similarity'], 0.9)
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'test-never-sent')
        self.assertEqual(similar_awards(tender)['results'], first['results'])
        self.assertEqual(post.call_count, 1)
        self.assertTrue(SimilarAwardsCache.objects.filter(tender=tender).exists())

    @patch('tenders.past_awards.requests.post')
    def test_gemini_failure_falls_back_to_text_without_leaking_key(self, post):
        post.return_value = MagicMock(status_code=403, text='key test-never-sent invalid')
        result = similar_awards(real_tender())
        self.assertEqual(result['mode'], 'text')
        self.assertIn('403', result['warning'])
        self.assertNotIn('test-never-sent', str(result))


class ViewTests(TestCase):
    @patch.dict('os.environ', {'GEMINI_API_KEY': ''})
    def test_endpoint_returns_payload_and_404(self):
        import_notices([notice(1)])
        real_tender()
        response = self.client.get('/api/tenders/pjn-dosje-99/similar-awards')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['winners'][0]['name'], 'Tiskarna d.o.o.')
        self.assertEqual(self.client.get('/api/tenders/missing/similar-awards').status_code, 404)


class BundleTests(TestCase):
    def test_bundle_roundtrip_loads_only_into_empty_table(self):
        import tempfile
        from pathlib import Path
        from .past_awards import ensure_past_awards, write_bundle
        import_notices([notice(1), notice(2, dossier=20, number='JN000002/2026-SL4/01')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bundle.json.gz'
            self.assertEqual(write_bundle(path), 2)
            first = path.read_bytes()
            write_bundle(path)
            self.assertEqual(path.read_bytes(), first)  # reproducible for Git
            self.assertEqual(ensure_past_awards(path), 0)  # existing data is never overwritten
            PastAward.objects.all().delete()
            self.assertEqual(ensure_past_awards(path), 2)
            self.assertEqual(PastAward.objects.get(pk='pjn-1-1').data['winners'][0]['name'], 'Tiskarna d.o.o.')
            self.assertEqual(ensure_past_awards(Path(tmp) / 'missing.json.gz'), 0)

    def test_shipped_bundle_is_readable(self):
        from .past_awards import BUNDLE, read_json
        rows = read_json(BUNDLE)
        self.assertGreater(len(rows), 1000)
        self.assertTrue(all(r['id'].startswith('pjn-') for r in rows[:50]))
