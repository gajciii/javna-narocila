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
