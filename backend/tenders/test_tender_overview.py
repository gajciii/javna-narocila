from copy import deepcopy
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import Document, DocumentChunk, IndexedContent, Tender, TenderOverview
from .tender_overview import overview


@override_settings(ACCOUNT_REQUIRE_LOGIN=False)
@patch('tenders.tender_overview.ai_enabled', return_value=True)
@patch('tenders.tender_overview.structured_call')
class TenderOverviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tender = Tender.objects.create(id='summary-example', data={
            'title': 'Vzdrževanje in nadgradnja informacijskega sistema',
            'summary': 'Vzdrževanje in nadgradnja informacijskega sistema',
            'description': 'Pogodba velja dve leti.', 'buyer': 'Občina Primer',
            'deadline': '2026-12-01T12:00:00+01:00', 'value': 100000,
            'source_type': 'real', 'version': 1})
        content = IndexedContent.objects.create(id='a' * 64, sha256='a' * 64, extractor_version='test',
            format='pdf', pages=[])
        self.doc = Document.objects.create(id='overview-doc', tender=self.tender, title='Specifikacija.pdf',
            path='/unavailable.pdf', version=1, status='processed', indexed_content=content)
        self.chunk = DocumentChunk.objects.create(content=content, ordinal=0, page=2, locator='stran 2',
            text='Storitev vključuje podporo uporabnikom in odpravo napak. Pogodba velja dve leti.',
            normalized_text='storitev vkljucuje podporo uporabnikom in odpravo napak. pogodba velja dve leti.')
        self.answer = {'sentences': [
            {'text': 'Predmet naročila je vzdrževanje in nadgradnja informacijskega sistema.',
             'evidence': [{'source_index': 0, 'quote': 'Vzdrževanje in nadgradnja informacijskega sistema'}]},
            {'text': 'Storitve vključujejo podporo uporabnikom in odpravo napak.',
             'evidence': [{'source_index': 1, 'quote': 'Storitev vključuje podporo uporabnikom in odpravo napak.'}]},
            {'text': 'Pogodbeno obdobje za izvajanje storitev traja dve leti.',
             'evidence': [{'source_index': 1, 'quote': 'Pogodba velja dve leti.'}]}]}

    def test_generated_overview_has_three_sentences_and_persistent_verified_sources(self, call, _enabled):
        call.return_value = self.answer
        first = overview(self.tender)
        self.assertEqual(first['mode'], 'live')
        self.assertEqual(len(first['sentences']), 3)
        saved = TenderOverview.objects.get(tender=self.tender)
        self.assertEqual(saved.citations[1]['document_id'], self.doc.pk)
        self.assertEqual(saved.citations[1]['page'], 2)
        self.assertEqual(overview(self.tender), first)
        self.assertEqual(call.call_count, 1)

    def test_changed_notice_invalidates_summary(self, call, _enabled):
        call.return_value = self.answer
        overview(self.tender)
        self.tender.data['description'] = 'Spremenjen opis predmeta naročila.'
        self.tender.save()
        overview(self.tender)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(TenderOverview.objects.count(), 1)

    def test_changed_document_invalidates_summary(self, call, _enabled):
        call.return_value = self.answer
        overview(self.tender)
        self.chunk.text = self.chunk.text.replace('dve leti', 'tri leta')
        self.chunk.save()
        changed = deepcopy(self.answer)
        changed['sentences'][2]['text'] = 'Pogodbeno obdobje za izvajanje storitev traja tri leta.'
        changed['sentences'][2]['evidence'][0]['quote'] = 'Pogodba velja tri leta.'
        call.return_value = changed
        result = overview(self.tender)
        self.assertEqual(call.call_count, 2)
        self.assertIn('tri leta', result['sentences'][2])

    def test_fabricated_citation_is_rejected_and_not_cached_as_ai(self, call, _enabled):
        bad = deepcopy(self.answer)
        bad['sentences'][1]['evidence'][0]['quote'] = 'Zahtevana je registracija na Marsu.'
        call.return_value = bad
        self.assertEqual(overview(self.tender)['mode'], 'source')
        self.assertFalse(TenderOverview.objects.exists())

    def test_wrong_sentence_count_is_rejected(self, call, _enabled):
        call.return_value = {'sentences': self.answer['sentences'][:2]}
        self.assertEqual(overview(self.tender)['mode'], 'source')
        self.assertFalse(TenderOverview.objects.exists())

    def test_outage_provides_three_to_five_source_sentences_and_limits_retries(self, call, _enabled):
        call.side_effect = TimeoutError
        result = overview(self.tender)
        self.assertEqual(result['mode'], 'source')
        self.assertGreaterEqual(len(result['sentences']), 3)
        self.assertLessEqual(len(result['sentences']), 5)
        self.assertTrue(any('Občina Primer' in sentence for sentence in result['sentences']))
        overview(self.tender)
        self.assertEqual(call.call_count, 1)

    def test_no_credentials_never_calls_provider(self, call, enabled):
        enabled.return_value = False
        self.assertEqual(overview(self.tender)['mode'], 'source')
        call.assert_not_called()

    def test_notice_change_during_generation_cannot_cache_outdated_summary(self, call, _enabled):
        def changed(*args, **kwargs):
            Tender.objects.filter(pk=self.tender.pk).update(data={**self.tender.data, 'version': 2})
            return self.answer
        call.side_effect = changed
        self.assertTrue(overview(self.tender)['pending'])
        self.assertFalse(TenderOverview.objects.exists())

    def test_endpoint_and_missing_tender(self, call, _enabled):
        call.return_value = self.answer
        response = self.client.get(f'/api/tenders/{self.tender.pk}/overview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['sentences']), 3)
        self.assertEqual(self.client.get('/api/tenders/missing/overview').status_code, 404)
