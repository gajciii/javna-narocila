from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .deep_relevance import fold
from .filtering import apply_filters
from .keyword_expansion import expand, query_stems
from .models import Document, DocumentChunk, IndexedContent, Tender


class KeywordExpansionTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='keyword-test', data={'version': 2})
        self.text = 'Dobava klimatskih naprav vključuje prezračevanje in hlajenje prostorov.'
        self.content = IndexedContent.objects.create(id='k' * 64, sha256='a' * 64,
            extractor_version='shared-v1', pages=[], format='pdf')
        self.doc = Document.objects.create(id='pjn-doc-keyword', tender=self.tender,
            title='Popis del.pdf', path='unused.pdf', version=2, status='processed',
            indexed_content=self.content, extraction={'format': 'pdf'})
        DocumentChunk.objects.create(content=self.content, ordinal=0, page=3,
            locator='stran 3', text=self.text, normalized_text=fold(self.text))
        # Production uses a PostgreSQL full text vector.
        from django.db import connection
        if connection.vendor == 'postgresql':
            from django.contrib.postgres.search import SearchVector
            self.content.chunks.update(search_vector=SearchVector('normalized_text', config='simple'))

    def answer(self, term='prezračevanje', **patches):
        return {'suggestions': [{'term': term, 'passage': 0, 'quote': self.text,
                                'reason': 'Povezana strojna instalacija.', **patches}]}

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    def test_expansion_is_grounded_and_returns_source(self, call, enabled):
        call.return_value = self.answer()
        response = APIClient().post('/api/searches/expand-keywords', {'q': 'klimatske naprave'}, format='json')
        self.assertEqual(response.status_code, 200)
        item = response.data['suggestions'][0]
        self.assertEqual(item['term'], 'prezračevanje')
        self.assertEqual(item['evidence']['document_id'], self.doc.pk)
        self.assertEqual(item['evidence']['page'], 3)
        self.assertIn(self.text, str(call.call_args.args[2]))

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    def test_unverified_duplicate_and_invalid_sources_are_rejected(self, call, enabled):
        for answer in [self.answer('izmišljena oprema'), self.answer(quote='Izmišljen citat prezračevanje'),
                       self.answer('Dobava klimatskih naprav vključuje prezračevanje'),
                       self.answer('Dobava klimatskih naprav'),
                       self.answer('klimatskih naprav'), self.answer('račevanje')]:
            call.return_value = answer
            result = expand('klimatskih naprav')
            self.assertEqual(result['suggestions'], [])

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    def test_longer_variant_of_a_suggested_term_is_dropped(self, call, enabled):
        quote = 'Dograditev sistema cevne zračne pošte in optimizacija delujoče cevne zračne pošte.'
        passage = {'document_id': self.doc.pk, 'quote': quote}
        items = [self.answer(term, quote=quote)['suggestions'][0] for term in
                 ['cevne zračne pošte', 'sistema cevne zračne pošte', 'delujoče cevne zračne pošte']]
        with patch('tenders.keyword_expansion.ranked_passages', return_value=[passage]):
            for ordered in [items, list(reversed(items))]:
                with self.subTest(order=[item['term'] for item in ordered]):
                    call.return_value = {'suggestions': ordered}
                    self.assertEqual([s['term'] for s in expand('cevna pošta, ')['suggestions']],
                                     ['cevne zračne pošte'])

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    def test_miscounted_passage_and_letter_case_still_cite_the_real_source(self, call, enabled):
        call.return_value = self.answer(passage=12, quote='DOBAVA KLIMATSKIH NAPRAV VKLJUČUJE PREZRAČEVANJE')
        item = expand('klimatske naprave')['suggestions'][0]
        self.assertEqual((item['term'], item['evidence']['document_id']), ('prezračevanje', self.doc.pk))

    @patch('tenders.keyword_expansion.structured_call')
    def test_missing_context_or_credentials_does_not_invent_terms(self, call):
        self.assertEqual(expand('tiskanje brošur')['suggestions'], [])
        with patch('tenders.keyword_expansion.ai_enabled', return_value=False):
            self.assertEqual(expand('klimatske naprave')['mode'], 'unavailable')
        call.assert_not_called()

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call', side_effect=TimeoutError)
    def test_provider_failure_returns_clear_message(self, call, enabled):
        self.assertEqual(expand('klimatske naprave')['mode'], 'unavailable')

    def test_retrieval_does_not_truncate_typed_terms(self):
        self.assertEqual(query_stems('robot'), {'robot'})
        self.assertEqual(query_stems('klimatske in naprave'), {'klimats', 'napra'})
        text = 'Ob robovih strehe se vgradi odkapni profil.'
        DocumentChunk.objects.create(content=self.content, ordinal=1, page=4,
            locator='stran 4', text=text, normalized_text=fold(text))
        with patch('tenders.keyword_expansion.ai_enabled', return_value=True), \
                patch('tenders.keyword_expansion.structured_call') as call:
            self.assertEqual(expand('robot')['suggestions'], [])
            call.assert_not_called()

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    def test_quote_with_different_line_breaks_is_accepted(self, call, enabled):
        call.return_value = self.answer(quote='klimatskih naprav vključuje\nprezračevanje')
        self.assertEqual(expand('klimatske naprave')['suggestions'][0]['term'], 'prezračevanje')

    def test_invalid_input(self):
        for query in ['', 'a', ['klima'], 'x' * 1001]:
            response = APIClient().post('/api/searches/expand-keywords', {'q': query}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_search_matches_document_text_and_ignores_obsolete_versions(self):
        tender = {'id': self.tender.pk, 'title': 'Gradnja šole', 'buyer': 'Občina',
                  'match': {'score': 50}, 'following': False}
        self.assertEqual(apply_filters([tender], {'view': 'all', 'q': 'prezračevanje'}), [tender])
        self.assertEqual(apply_filters([tender], {'view': 'all', 'q': 'tiskanje'}), [])
        self.doc.version = 1
        self.doc.save()
        self.assertEqual(apply_filters([tender], {'view': 'all', 'q': 'prezračevanje'}), [])
        with patch('tenders.keyword_expansion.structured_call') as call:
            self.assertEqual(expand('klimatske naprave')['suggestions'], [])
            call.assert_not_called()

    def test_search_reports_each_found_term_with_citation(self):
        from .filtering import keyword_matches
        from .keyword_expansion import document_keyword_hits, quote_around
        hits = document_keyword_hits(['prezračevanje', 'hlajenje', 'tiskanje'], [self.tender.pk])
        evidence = hits[self.tender.pk]['prezracevanje']
        self.assertEqual((evidence['document_id'], evidence['page']), (self.doc.pk, 3))
        self.assertEqual(evidence['quote'][evidence['match_start']:evidence['match_end']], 'prezračevanje')
        self.assertNotIn('tiskanje', hits[self.tender.pk])
        tender = {'id': self.tender.pk, 'title': 'Hlajenje šole', 'buyer': 'Občina', 'topics': ['klima']}
        found = keyword_matches(tender, 'Prezračevanje, hlajenje, tiskanje, klima', hits[self.tender.pk])
        self.assertEqual([item['term'] for item in found], ['Prezračevanje', 'hlajenje', 'klima'])
        self.assertEqual(found[1]['fields'], ['naslovu'])
        self.assertIsNone(found[2]['evidence'])
        long = 'uvod ' * 60 + 'robotski sistem' + ' zaključek' * 60
        excerpt = quote_around(long, 'robotski')
        self.assertTrue(excerpt['quote'].startswith('… ') and excerpt['quote'].endswith(' …'))
        self.assertEqual(excerpt['quote'][excerpt['match_start']:excerpt['match_end']], 'robotski')

    def test_tender_list_returns_keyword_matches_only_when_searching(self):
        from .seed import ensure_seed
        self.tender.delete()  # The bare fixture tender has no listing fields.
        ensure_seed()
        response = APIClient().get('/api/tenders', {'view': 'all', 'q': 'IoT'})
        self.assertTrue(response.data['results'])
        self.assertTrue(all(item['keyword_matches'] for item in response.data['results']))
        self.assertNotIn('keyword_matches', APIClient().get('/api/tenders', {'view': 'all'}).data['results'][0])


class VectorPassageTests(TestCase):
    """Passages by meaning (pgvector in production) plus titles of similar past contracts."""
    def setUp(self):
        from .models import PastAward
        tender = Tender.objects.create(id='vector-test', data={'version': 1})
        content = IndexedContent.objects.create(id='v' * 64, sha256='b' * 64, extractor_version='shared-v1', pages=[], format='pdf')
        Document.objects.create(id='pjn-doc-vector', tender=tender, title='Tehnične zahteve.pdf', path='unused.pdf',
                                version=1, status='processed', indexed_content=content, extraction={'format': 'pdf'})
        self.text = 'Sistem pnevmatskega transporta vzorcev povezuje laboratorij in oddelke.'
        self.chunk = DocumentChunk.objects.create(content=content, ordinal=0, page=2, locator='stran 2', text=self.text,
                                                  normalized_text=fold(self.text), embedding=[0.5] * 1024)
        from django.db import connection
        if connection.vendor == 'postgresql':
            from django.contrib.postgres.search import SearchVector
            content.chunks.update(search_vector=SearchVector('normalized_text', config='simple'))
        self.award = PastAward.objects.create(id='a1', notice_id='77', data={'title': 'Dograditev sistema cevne zračne pošte',
                                              'notice_number': 'JN000077/2025', 'buyer': 'SB Novo mesto'})

    def nearest(self, queryset, text, limit):
        return [self.chunk] if queryset.model is DocumentChunk else [self.award]

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call')
    @patch('tenders.keyword_expansion.lexical_chunks', return_value=[])
    @patch('tenders.embeddings.enabled', return_value=True)
    def test_meaning_finds_passages_and_award_titles_without_shared_words(self, enabled, lexical, call, ai):
        call.return_value = {'suggestions': [
            {'term': 'pnevmatskega transporta', 'passage': 0, 'quote': self.text, 'reason': 'Druga oblika cevne pošte.'},
            {'term': 'cevne zračne pošte', 'passage': 1, 'quote': 'Dograditev sistema cevne zračne pošte', 'reason': 'Sopomenka.'}]}
        with patch('tenders.embeddings.nearest', side_effect=self.nearest):
            result = expand('cevna pošta')
        self.assertEqual([s['term'] for s in result['suggestions']], ['pnevmatskega transporta', 'cevne zračne pošte'])
        self.assertEqual(result['suggestions'][0]['evidence']['document_id'], 'pjn-doc-vector')
        award = result['suggestions'][1]['evidence']
        self.assertEqual((award['document_id'], award['document_url']), ('', 'https://www.enarocanje.si/#/pregled-objav/77'))
        self.assertEqual(call.call_args.kwargs['reasoning'], 'low')

    @patch('tenders.keyword_expansion.ai_enabled', return_value=True)
    @patch('tenders.keyword_expansion.structured_call', return_value={'suggestions': []})
    @patch('tenders.embeddings.enabled', return_value=True)
    def test_vector_failure_falls_back_to_word_search(self, enabled, call, ai):
        with patch('tenders.embeddings.nearest', side_effect=RuntimeError('provider down')):
            result = expand('pnevmatskega transporta')
        self.assertEqual(result['mode'], 'live')
        self.assertIn(self.text, str(call.call_args.args[2]))
