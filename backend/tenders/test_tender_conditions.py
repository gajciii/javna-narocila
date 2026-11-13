from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .deep_relevance import fold
from .models import Document, DocumentChunk, IndexedContent, Tender, TenderConditions
from .tender_conditions import conditions_payload, extract_conditions

TEXT = ('Pogoji za sodelovanje: ponudnik mora predložiti najmanj 2 referenci za izvedbo podobnih del '
        'v zadnjih 5 letih. Ponudnik mora imeti zaposlene najmanj 3 strokovnjake.')


def condition(**changes):
    item = {'category': 'technical', 'title': 'Reference podobnih del',
            'requirement': 'Najmanj 2 referenci v zadnjih 5 letih.', 'passage': 0,
            'quote': 'najmanj 2 referenci za izvedbo podobnih del',
            'check': {'kind': 'reference_count', 'minimum': 2, 'domain': None, 'max_age_years': 5,
                      'technologies': [], 'certification': None}}
    return {**item, **changes}


class TenderConditionTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='cond-test', data={'version': 1, 'title': 'Gradnja', 'status': 'open'})
        self.content = IndexedContent.objects.create(id='c' * 64, sha256='b' * 64,
            extractor_version='shared-v1', pages=[], format='pdf')
        Document.objects.create(id='pjn-doc-cond', tender=self.tender, title='Navodila.pdf', path='x.pdf',
            version=1, status='processed', indexed_content=self.content, extraction={'format': 'pdf'})
        DocumentChunk.objects.create(content=self.content, ordinal=0, page=7, locator='stran 7',
            text=TEXT, normalized_text=fold(TEXT))
        from django.db import connection
        if connection.vendor == 'postgresql':
            from django.contrib.postgres.search import SearchVector
            self.content.chunks.update(search_vector=SearchVector('normalized_text', config='simple'))

    @patch('tenders.tender_conditions.ai_enabled', return_value=True)
    @patch('tenders.tender_conditions.structured_call')
    def test_conditions_are_grounded_and_invalid_ones_dropped(self, call, enabled):
        call.return_value = {'conditions': [
            condition(),
            condition(title='Strokovnjaki', category='technical', quote='zaposlene najmanj 3\nstrokovnjake',
                      check={'kind': 'staff', 'minimum': 'tri', 'domain': None, 'max_age_years': None,
                             'technologies': [], 'certification': None}),
            condition(title='Izmišljen pogoj', quote='zavarovanje za resnost ponudbe'),
            condition(title='Napačen odlomek', passage=4),
            condition(title='Reference podobnih del'),
        ]}
        record = extract_conditions(self.tender)
        self.assertEqual(record.mode, 'live')
        # A wrong passage index is corrected from the verbatim quote; an unquoted condition is dropped.
        self.assertEqual([c['title'] for c in record.conditions], ['Reference podobnih del', 'Strokovnjaki', 'Napačen odlomek'])
        self.assertEqual(record.conditions[0]['page'], 7)
        # An unusable threshold keeps the condition but does not evaluate it.
        self.assertEqual(record.conditions[1]['check'], {'kind': 'none'})

        call.reset_mock()
        extract_conditions(self.tender)
        call.assert_not_called()

        payload = conditions_payload(self.tender, {'references': []})
        self.assertEqual(payload['items'][0]['status'], 'unknown')
        self.assertEqual(payload['items'][1]['status'], 'manual')
        self.assertEqual(payload['items'][0]['category_label'], 'Tehnična in strokovna sposobnost')

    @patch('tenders.tender_conditions.ai_enabled', return_value=True)
    @patch('tenders.tender_conditions.structured_call', side_effect=TimeoutError)
    def test_provider_failure_is_recorded_and_retried(self, call, enabled):
        self.assertEqual(extract_conditions(self.tender).mode, 'unavailable')
        extract_conditions(self.tender)
        self.assertEqual(call.call_count, 2)

    def test_detail_returns_condition_list(self):
        TenderConditions.objects.create(tender=self.tender, fingerprint='old', mode='live', extracted_at='2026-11-12T00:00Z',
            conditions=[{**condition(), 'id': 'c1', 'document_id': 'pjn-doc-cond', 'document_title': 'Navodila.pdf',
                         'page': 7, 'locator': 'stran 7', 'check': {'kind': 'none'}}])
        data = APIClient().get('/api/tenders/cond-test').data['tender_conditions']
        self.assertEqual(data['items'][0]['status'], 'manual')
        self.assertFalse(data['current'])


def stored(id, **changes):
    return {**condition(**changes), 'id': id, 'document_id': 'pjn-doc-cond', 'document_title': 'Navodila.pdf',
            'page': 7, 'locator': 'stran 7', 'check': {'kind': 'none'}}


class ConditionAnswerTests(TestCase):
    def setUp(self):
        from .seed import ensure_seed
        ensure_seed()
        self.client = APIClient()
        base = {'version': 1, 'status': 'open', 'buyer': 'Občina', 'region': 'Slovenija', 'kind': 'services',
                'cpv': [], 'value': None, 'published_at': '2026-11-01', 'deadline': '2099-01-01', 'summary': '',
                'topics': [], 'technologies': [], 'criteria': [], 'lots': [], 'source_type': 'real'}
        self.first = Tender.objects.create(id='answer-a', data={**base, 'title': 'Prvi razpis'})
        self.second = Tender.objects.create(id='answer-b', data={**base, 'title': 'Drugi razpis'})
        TenderConditions.objects.create(tender=self.first, fingerprint='x', mode='live', extracted_at='2026-11-12T00:00Z', conditions=[
            stored('c1', category='economic', title='Povprečni letni promet',
                   requirement='Povprečni letni promet v zadnjih treh letih najmanj 500.000 EUR.'),
            stored('c2', category='exclusion', title='Ponudnik ni bil pravnomočno obsojen',
                   requirement='Ponudnik ali njegov zakoniti zastopnik ni bil pravnomočno obsojen zaradi kaznivih dejanj iz prvega odstavka 75. člena ZJN-3.')])
        TenderConditions.objects.create(tender=self.second, fingerprint='x', mode='live', extracted_at='2026-11-12T00:00Z', conditions=[
            stored('c1', category='exclusion', title='Ponudnik ni bil pravnomočno obsojen',
                   requirement='Ponudnik in njegov zakoniti zastopnik nista bila pravnomočno obsojena zaradi kaznivih dejanj.'),
            stored('c2', category='economic', title='Povprečni letni promet',
                   requirement='Povprečni letni promet v zadnjih treh letih najmanj 2.000.000 EUR.'),
            stored('c3', category='technical', title='Certifikat ISO 9001')])

    def answer(self, tender, condition_id, answer):
        return self.client.post(f'/api/tenders/{tender}/conditions/{condition_id}/answer', {'answer': answer}, format='json')

    def items(self, tender):
        return {item['id']: item for item in self.client.get(f'/api/tenders/{tender}').data['tender_conditions']['items']}

    def test_answer_is_saved_to_profile_and_reused_for_similar_conditions(self):
        response = self.answer('answer-a', 'c2', 'met')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['profile']['condition_answers'][0]['answer'], 'met')
        own = {item['id']: item for item in response.data['tender']['tender_conditions']['items']}['c2']
        self.assertEqual(own['status'], 'met')
        self.assertFalse(own['profile_answer']['inherited'])

        items = self.items('answer-b')
        # Same condition worded differently in another tender, without the article reference.
        self.assertEqual(items['c1']['status'], 'met')
        self.assertTrue(items['c1']['profile_answer']['inherited'])
        self.assertEqual(items['c1']['profile_answer']['tender_title'], 'Prvi razpis')
        self.assertIsNone(items['c3']['profile_answer'])

    def test_different_threshold_is_not_inherited(self):
        self.answer('answer-a', 'c1', 'met')
        items = self.items('answer-b')
        self.assertIsNone(items['c2']['profile_answer'])
        self.assertEqual(items['c2']['status'], 'manual')

    def test_unmet_answer_marks_other_tenders_unsuitable(self):
        self.answer('answer-a', 'c2', 'unmet')
        detail = self.client.get('/api/tenders/answer-b').data
        self.assertEqual(detail['match']['recommendation'], 'unsuitable')
        self.assertIn('Ponudnik ni bil pravnomočno obsojen', detail['match']['open_question'])
        listed = {t['id']: t for t in self.client.get('/api/tenders?view=all').data['results']}
        self.assertEqual(listed['answer-b']['match']['recommendation'], 'unsuitable')

    def test_override_and_removal(self):
        self.answer('answer-a', 'c2', 'met')
        # Marking the inherited condition differently stores a separate answer for this wording.
        self.answer('answer-b', 'c1', 'unmet')
        self.assertEqual(self.items('answer-b')['c1']['status'], 'unmet')
        self.assertEqual(self.items('answer-a')['c2']['status'], 'met')
        response = self.answer('answer-b', 'c1', None)
        self.assertEqual(len(response.data['profile']['condition_answers']), 1)
        self.assertEqual(self.items('answer-b')['c1']['status'], 'met')
        answer_id = response.data['profile']['condition_answers'][0]['id']
        profile = self.client.delete(f'/api/profile/condition-answers/{answer_id}').data
        self.assertEqual(profile['condition_answers'], [])
        self.assertEqual(self.items('answer-b')['c1']['status'], 'manual')

    def test_profile_save_keeps_answers_and_invalid_answer_is_rejected(self):
        self.answer('answer-a', 'c2', 'met')
        profile = self.client.get('/api/bootstrap').data['profile']
        saved = self.client.put('/api/profile', {**profile, 'condition_answers': []}, format='json').data
        self.assertEqual(len(saved['condition_answers']), 1)
        self.assertEqual(self.answer('answer-a', 'c2', 'maybe').status_code, 400)
        self.assertEqual(self.answer('answer-a', 'c9', 'met').status_code, 404)
