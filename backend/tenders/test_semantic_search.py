from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from . import semantic_search
from .filtering import apply_filters
from .seed import ensure_seed
from .semantic_search import semantic_matches
from .services import all_tenders


def scores(values, rest=0.3):
    """similarities() stand-in: fixed scores for the given tenders, ``rest`` for every other one."""
    return lambda model, term, ids: {pk: values.get(pk, rest) for pk in ids}


@patch('tenders.embeddings.enabled', return_value=True)
class SemanticSearchTests(TestCase):
    def setUp(self):
        ensure_seed()
        semantic_search._down_until = 0.0

    def test_only_tenders_close_to_the_best_match_are_kept(self, enabled):
        values = {'a': 0.70, 'b': 0.66, 'c': 0.63, 'd': 0.40, 'e': 0.35, 'f': 0.34, 'g': 0.30}
        with patch('tenders.embeddings.similarities', side_effect=scores(values)):
            found = semantic_matches(['klimatizacija'], list(values))
        self.assertEqual(set(found), {'a', 'b'})  # c is more than MARGIN below the best match
        self.assertEqual(found['a'], {'term': 'klimatizacija', 'similarity': 0.7})

    def test_query_without_a_good_match_adds_nothing(self, enabled):
        # "cevna pošta" in production: the best tender is unrelated and stays below the floor.
        with patch('tenders.embeddings.similarities', side_effect=scores({'a': 0.51, 'b': 0.30, 'c': 0.28})):
            self.assertEqual(semantic_matches(['cevna pošta'], ['a', 'b', 'c']), {})

    def test_generic_query_that_resembles_every_tender_adds_nothing(self, enabled):
        # "svetovanje pri javnem naročanju": the best match is high but barely above the median.
        values = {'a': 0.60, 'b': 0.58, 'c': 0.50, 'd': 0.48, 'e': 0.47}
        with patch('tenders.embeddings.similarities', side_effect=scores(values)):
            self.assertEqual(semantic_matches(['svetovanje pri javnem naročanju'], list(values)), {})

    def test_short_terms_are_not_embedded(self, enabled):
        with patch('tenders.embeddings.similarities') as similarities:
            self.assertEqual(semantic_matches(['CZP', 'IoT'], ['a']), {})
        similarities.assert_not_called()

    def test_provider_failure_falls_back_and_pauses(self, enabled):
        with patch('tenders.embeddings.similarities', side_effect=TimeoutError) as similarities:
            self.assertEqual(semantic_matches(['klimatizacija'], ['a']), {})
            self.assertEqual(semantic_matches(['klimatizacija'], ['a']), {})
        self.assertEqual(similarities.call_count, 1)

    def test_list_keeps_word_matches_first_and_marks_meaning_only(self, enabled):
        tenders = all_tenders()
        word_match = apply_filters(tenders, {'view': 'all', 'q': 'IoT'})
        self.assertTrue(word_match)
        other = next(t['id'] for t in tenders if t['id'] not in {w['id'] for w in word_match} and not t.get('ignored'))
        values = {other: 0.8, word_match[0]['id']: 0.79}
        hits = {}
        with patch('tenders.embeddings.similarities', side_effect=scores(values)):
            result = apply_filters(tenders, {'view': 'all', 'q': 'IoT, senzorika'}, semantic_hits=hits)
        ids = [t['id'] for t in result]
        self.assertIn(other, ids)
        self.assertEqual(ids[-1], other)
        self.assertEqual(hits, {other: {'term': 'senzorika', 'similarity': 0.8}})

    def test_without_semantic_hits_the_filter_stays_word_only(self, enabled):
        with patch('tenders.embeddings.similarities') as similarities:
            apply_filters(all_tenders(), {'view': 'all', 'q': 'senzorika'})
        similarities.assert_not_called()

    def test_api_returns_semantic_match(self, enabled):
        target = next(t['id'] for t in all_tenders() if not t.get('ignored'))
        with patch('tenders.embeddings.similarities', side_effect=scores({target: 0.75})):
            results = APIClient().get('/api/tenders', {'view': 'all', 'q': 'nekaj povsem drugega'}).data['results']
            detail = APIClient().get(f'/api/tenders/{target}', {'q': 'nekaj povsem drugega'}).data
        self.assertEqual([(t['id'], t['keyword_matches'], t['semantic_match']['term']) for t in results],
                         [(target, [], 'nekaj povsem drugega')])
        self.assertEqual(detail['semantic_match']['similarity'], 0.75)
