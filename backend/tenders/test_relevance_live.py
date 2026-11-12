import os
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from .matching import serialize_tender
from .models import RelevanceCache, Tender
from .relevance import resolve_matches, score_answer
from .pjn_sync import persist_notice
from .seed import ensure_seed, get_profile
from .services import all_tenders


@patch.dict(os.environ, {'GEMINI_API_KEY': 'test-never-sent', 'GEMINI_DECISION_MODEL': ''})
class LiveRelevanceTests(TestCase):
    def setUp(self):
        ensure_seed()

    @patch('tenders.relevance.requests.post')
    def test_one_batch_is_cached_and_invalidated_by_profile_or_tender_change(self, post):
        def response(*args, **kwargs):
            questions = kwargs['json']['questions']
            return MagicMock(status_code=200, json=lambda: {'answers': {
                qid: {'probabilities': {'0': 0.1, '1': 0.2, '2': 0.7}} for qid in questions}})
        post.side_effect = response
        profile = get_profile()
        first = all_tenders(profile)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(first), 7)
        self.assertTrue(all(t['match']['mode'] == 'gemini' for t in first))
        self.assertEqual(first[0]['match']['level'], 'high')
        self.assertEqual(first[0]['match']['recommendation'], 'recommended')
        sent = post.call_args.kwargs['json']['input']
        self.assertNotIn(profile['name'], sent)
        self.assertNotIn(profile['registration_number'], sent)
        self.assertNotIn(profile['address'], sent)
        self.assertNotIn('Energetski nadzor javnih objektov', sent)
        self.assertEqual(RelevanceCache.objects.count(), 7)
        all_tenders(profile)
        self.assertEqual(post.call_count, 1)

        changed = {**profile, 'description': profile['description'] + ' Optična omrežja.'}
        all_tenders(changed)
        self.assertEqual(post.call_count, 2)
        tender = Tender.objects.get(pk='energy-iot')
        tender.data = {**tender.data, 'summary': tender.data['summary'] + ' Nova storitev.'}
        tender.save(update_fields=['data'])
        serialize_tender(tender, changed)
        self.assertEqual(post.call_count, 3)

    @patch('tenders.relevance.requests.post')
    def test_ai_content_decision_does_not_override_document_conditions(self, post):
        post.return_value = MagicMock(status_code=200, json=lambda: {'answers': {
            'q0': {'probabilities': {'0': 0.05, '1': 0.15, '2': 0.8}}}})
        sport = Tender.objects.get(pk='sport-portal')
        result = serialize_tender(sport, get_profile())
        self.assertEqual(result['match']['mode'], 'gemini')
        self.assertEqual(result['match']['level'], 'high')
        self.assertEqual(result['match']['recommendation'], 'review')
        self.assertTrue(any(c['status'] == 'unknown' for c in result['match']['conditions']))

    @patch('tenders.relevance.requests.post')
    def test_ai_low_fit_excludes_otherwise_qualified_tender(self, post):
        post.return_value = MagicMock(status_code=200, json=lambda: {'answers': {
            'q0': {'probabilities': {'0': 0.85, '1': 0.1, '2': 0.05}}}})
        result = serialize_tender(Tender.objects.get(pk='energy-iot'), get_profile())
        self.assertEqual(result['match']['recommendation'], 'unsuitable')
        self.assertEqual(result['match']['level'], 'low')

    @patch('tenders.relevance.requests.post')
    def test_collection_does_not_wait_for_gemini(self, post):
        data = dict(Tender.objects.get(pk='energy-iot').data)
        data.update(id='pjn-dosje-1001', source_type='real', source_metadata={
            'notice_id': '1001', 'dossier_id': 1001, 'published_timestamp': timezone.now().isoformat(),
            'fetched_at': timezone.now().isoformat(), 'attachment_url': None})
        record, created, changed = persist_notice(data)
        self.assertTrue(created and changed)
        self.assertEqual(record.pk, 'pjn-dosje-1001')
        post.assert_not_called()
        cached = resolve_matches([record], get_profile(), cached_only=True)
        self.assertEqual(cached[record.pk]['mode'], 'rules')
        post.assert_not_called()

    @patch('tenders.relevance.requests.post')
    def test_model_failure_uses_labelled_rules_and_short_retry_cache(self, post):
        post.return_value = MagicMock(status_code=403, text='key test-never-sent', json=lambda: {})
        tender = Tender.objects.get(pk='energy-iot')
        first = serialize_tender(tender, get_profile())
        self.assertEqual(first['match']['mode'], 'rules')
        self.assertIn('pravila', first['match']['warning'])
        self.assertNotIn('test-never-sent', str(first))
        serialize_tender(tender, get_profile())
        self.assertEqual(post.call_count, 1)

    @patch.dict(os.environ, {'GEMINI_API_KEY': ''})
    def test_no_key_keeps_existing_rules_without_cache_write(self):
        tender = Tender.objects.get(pk='energy-iot')
        result = serialize_tender(tender, get_profile())
        self.assertEqual((result['match']['mode'], result['match']['recommendation']), ('rules', 'recommended'))
        self.assertFalse(RelevanceCache.objects.exists())

    def test_conservative_label_and_score_remain_consistent(self):
        low = score_answer({'probabilities': {'0': 0.8, '1': 0.1, '2': 0.1}})
        review = score_answer({'probabilities': {'0': 0.25, '1': 0.35, '2': 0.4}})
        high = score_answer({'probabilities': {'0': 0.1, '1': 0.4, '2': 0.5}})
        self.assertEqual((low['level'], review['level'], high['level']), ('low', 'medium', 'high'))
        self.assertLess(low['score'], 40)
        self.assertTrue(40 <= review['score'] < 70)
        self.assertGreaterEqual(high['score'], 70)
