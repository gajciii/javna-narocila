"""Similar past awards; no network or real API key is used."""
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from .models import PastAward, SimilarAwardsCache, Tender
from .past_awards import from_pjn, import_notices, normalize_notice, similar_awards, summarize
from .pjn_sync import collect_notice, sync_awards
from .seed import ensure_seed

# Real PJN obrazecGet response (notice 1230270, three of five lots), trimmed to the fields that are read.
PJN_AWARD = json.loads((Path(__file__).parent / 'fixtures' / 'pjn-award.json').read_text(encoding='utf-8'))


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


class PjnAwardTests(TestCase):
    def test_official_award_notice_matches_the_scraper_normalization(self):
        rows = normalize_notice(from_pjn(PJN_AWARD))
        self.assertEqual([r['id'] for r in rows], ['pjn-1230270-613851', 'pjn-1230270-613852', 'pjn-1230270-613853'])
        row = rows[2]
        self.assertEqual((row['notice_id'], row['dossier_id'], row['published_on']), ('1230270', '646581', date(2026, 11, 11)))
        data = row['data']
        self.assertEqual(data['notice_number'], 'JN006625/2026-SL2/01')
        self.assertEqual(data['lot_title'], 'MATERIAL ZA OSKRBO RANE')
        self.assertEqual((data['buyer'], data['buyer_registration_number']), ('KOROŠKI DOM STAROSTNIKOV', '5049679000'))
        self.assertEqual((data['kind'], data['procedure'], data['framework'], data['currency']), ('goods', 'Naročilo male vrednosti', False, 'EUR'))
        self.assertEqual(len(data['cpv']), 1)
        self.assertEqual((data['estimated_value'], data['awarded_value'], data['lowest_offer'], data['highest_offer'], data['tenders_received']),
                         (27000.0, 23374.88, 23374.88, 25260.54, 2))
        self.assertTrue(data['awarded'])
        self.assertEqual(data['winners'], [{'name': 'SANOLABOR, podjetje za prodajo medicinskih, laboratorijskih in farmacevtskih proizvodov, d.d.',
                                            'registration_number': '5000823000'}])

    def test_unawarded_lots_framework_and_other_phases(self):
        raw = deepcopy(PJN_AWARD)
        raw['obrazecOddaja'][0].update(idSifOddajaStatus=1, obrazecOddajaSubjekt=[], vrednostIzbrana=None)
        raw['obrazecSklop'][1]['idSifSporazum'] = 3
        rows = {r['id']: r['data'] for r in normalize_notice(from_pjn(raw))}
        self.assertFalse(rows['pjn-1230270-613851']['awarded'])
        self.assertEqual(rows['pjn-1230270-613851']['winners'], [])
        self.assertTrue(rows['pjn-1230270-613852']['framework'])
        self.assertIsNone(from_pjn({**PJN_AWARD, 'idSifPostopekFaza': 3}))  # call for competition
        self.assertIsNone(from_pjn({'id': 'x'}))

    @patch('tenders.pjn_sync.fetch_json')
    def test_collected_award_notice_is_also_recorded_as_past_award(self, fetch_json):
        ensure_seed()
        fetch_json.return_value = deepcopy(PJN_AWARD)
        self.assertEqual(collect_notice('1230270', download=False)['mode'], 'live')
        self.assertEqual(Tender.objects.get(pk='pjn-dosje-646581').data['status'], 'closed')
        self.assertEqual(PastAward.objects.filter(notice_id='1230270').count(), 3)

    @patch('tenders.pjn_sync.fetch_json')
    def test_rejected_notice_is_not_stored_but_award_is_recorded(self, fetch_json):
        ensure_seed()
        fetch_json.return_value = deepcopy(PJN_AWARD)
        self.assertEqual(collect_notice('1230270', download=False, accept=lambda data: False)['mode'], 'skipped')
        self.assertFalse(Tender.objects.filter(pk='pjn-dosje-646581').exists())
        self.assertEqual(PastAward.objects.filter(notice_id='1230270').count(), 3)

    @patch('tenders.pjn_sync.import_notices', side_effect=RuntimeError)
    @patch('tenders.pjn_sync.fetch_json')
    def test_award_recording_failure_never_breaks_tender_collection(self, fetch_json, _):
        ensure_seed()
        fetch_json.return_value = deepcopy(PJN_AWARD)
        result = collect_notice('1230270', download=False)
        self.assertEqual(result['mode'], 'live', result.get('warning'))

    @patch('tenders.pjn_sync.sleep')
    @patch('tenders.pjn_sync.fetch_json')
    def test_window_sync_skips_known_notices_pages_and_keeps_going_after_errors(self, fetch_json, _):
        import_notices([notice(notice_id=500)])  # published 2026-10-01
        second = {**deepcopy(PJN_AWARD), 'id': 1230271}
        calls = []

        def respond(path, body=None):
            calls.append(path)
            if body is not None:
                self.assertEqual(body['idSifPostopekFaza'], [1])
                self.assertEqual(body['objavaDejanskaDatumOd'], '2026-09-29T00:00:00')  # newest award minus overlap
                self.assertEqual(body['objavaDejanskaDatumDo'], '2026-11-12T00:00:00')
                rows = [{'idObrazec': 500}, {'idObrazec': 1230270}] if body['startRow'] == 0 else [{'idObrazec': 1230271}, {'idObrazec': 77}]
                return {'data': rows, 'lastRow': 4}
            if path.endswith('=77'):
                raise ValueError('Portal e-Naročanje je vrnil HTTP 500.')
            return deepcopy(PJN_AWARD) if path.endswith('=1230270') else second

        fetch_json.side_effect = respond
        with patch('tenders.pjn_sync.AWARD_PAGE', 2):
            result = sync_awards(until=date(2026, 11, 11))
        self.assertEqual((result['listed'], result['fetched'], result['notices'], result['lots']), (4, 3, 2, 6))
        self.assertEqual(result['errors'], [{'notice_id': '77', 'message': 'Portal e-Naročanje je vrnil HTTP 500.'}])
        self.assertNotIn('obrazec/objava/obrazecGet?id=500', calls)
        self.assertEqual(PastAward.objects.filter(notice_id__in=['1230270', '1230271']).count(), 6)
        with self.assertRaises(ValueError):
            sync_awards(since=date(2026, 11, 12), until=date(2026, 11, 11))


class SummaryTests(TestCase):
    def test_value_totals_use_the_same_comparable_awards_for_both_amounts(self):
        base = {'awarded': True, 'framework': False, 'currency': 'EUR', 'estimated_value': 100,
                'awarded_value': 80, 'lowest_offer': None, 'highest_offer': None,
                'tenders_received': None, 'winners': []}
        summary = summarize([
            base, {**base, 'estimated_value': 300, 'awarded_value': 360},
            {**base, 'awarded_value': 100},
            {**base, 'award_currency': 'EUR', 'estimate_currency': 'USD'},
            {**base, 'estimated_value': None},
            {**base, 'awarded': False},
            {**base, 'framework': True},
        ])
        self.assertEqual(summary['price_to_estimate_count'], 3)
        self.assertEqual(summary['value_totals'], {'estimated': 500, 'contracted': 540, 'difference': 40,
            'ratio': 1.08, 'below': 1, 'equal': 1, 'above': 1})

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


@patch.dict('os.environ', {'GEMINI_API_KEY': ''})
class SimilarSemanticTests(TestCase):
    def setUp(self):
        import_notices([notice(1), notice(5, title='Izdelava promocijskih tiskovin', cpv='22462000 - Reklamni material', dossier=50,
                                         number='JN000005/2026-SL4/01'),
                        notice(3, title='Tiskarske storitve', dossier=99, number='JN000099/2026-EUe29/01')])

    def test_meaning_adds_awards_without_shared_words(self):
        nearest = lambda data: [(0.82, PastAward.objects.get(notice_id='5'))]  # noqa: E731
        with patch('tenders.past_awards.vector_candidates', side_effect=nearest):
            result = similar_awards(real_tender())
        self.assertEqual(result['matching'], 'semantic')
        # Notice 1 matches by words and the exact CPV code, notice 5 only by meaning; the own procedure stays out.
        self.assertEqual([r['notice_id'] for r in result['results']], ['1', '5'])
        self.assertEqual(result['results'][1]['similarity'], 0.82)

    def test_vector_failure_keeps_word_matches(self):
        with patch('tenders.past_awards.vector_candidates', side_effect=RuntimeError('provider down')):
            result = similar_awards(real_tender())
        self.assertEqual((result['matching'], [r['notice_id'] for r in result['results']]), ('text', ['1']))


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
