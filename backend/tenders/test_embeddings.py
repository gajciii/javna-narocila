from datetime import date
from unittest.mock import patch

from django.test import TestCase

from tenders import embeddings
from tenders.models import DocumentChunk, IndexedContent, PastAward, Tender
from tenders.past_awards import import_notices


def fake_embed(texts, timeout=60):
    return [[0.5] * embeddings.DIMENSIONS for _ in texts]


@patch('tenders.embeddings.enabled', return_value=True)
@patch('tenders.embeddings.embed', side_effect=fake_embed)
class EmbedPendingTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='t1', data={'title': 'Dograditev cevne pošte', 'buyer': 'SB Novo mesto'})
        content = IndexedContent.objects.create(pk='c1', sha256='a' * 64, extractor_version='shared-v1', pages=[], format='txt')
        for i in range(3):
            DocumentChunk.objects.create(content=content, ordinal=i, page=1, locator='stran 1', text=f'Odlomek {i}', normalized_text=f'odlomek {i}')
        PastAward.objects.create(id='a1', notice_id='1', published_on=date(2025, 1, 5), data={'title': 'Servis opreme'})

    def drain(self):
        while embeddings.embed_pending(limit=2):
            pass

    def test_fills_tenders_then_chunks_then_awards(self, embed, _):
        self.drain()
        self.assertEqual([len(call.args[0]) for call in embed.call_args_list], [1, 2, 1, 1])
        self.assertIn('Dograditev cevne pošte', embed.call_args_list[0].args[0][0])
        self.assertEqual(embeddings.pending_counts(), {'tenders': 0, 'chunks': 0, 'awards': 0})
        self.assertTrue(Tender.objects.get(pk='t1').embedding_digest)

    def test_changed_tender_text_is_embedded_again(self, embed, _):
        self.drain()
        embed.reset_mock()
        self.tender.data['summary'] = 'Pnevmatski transport vzorcev.'
        self.tender.save()
        self.assertEqual(embeddings.pending_counts()['tenders'], 1)
        self.drain()
        self.assertEqual(embed.call_count, 1)
        self.tender.following = True
        self.tender.save()  # Fields outside the embedded text do not trigger a new vector.
        self.assertEqual(embeddings.pending_counts()['tenders'], 0)

    def test_disabled_does_nothing(self, embed, enabled):
        enabled.return_value = False
        self.assertEqual(embeddings.embed_pending(), 0)
        embed.assert_not_called()


class AwardInvalidationTests(TestCase):
    def test_only_changed_award_text_resets_vector(self):
        data = {'title': 'Servis opreme', 'buyer': 'ZD Maribor'}
        award = PastAward.objects.create(id='a1', notice_id='1', data=data, embedding=[0.5] * embeddings.DIMENSIONS,
                                         embedding_digest=embeddings.digest(embeddings.award_text(data)))
        self.assertEqual(embeddings.award_invalidation(award, {**data, 'participants': [1]}), {})
        self.assertEqual(embeddings.award_invalidation(award, {**data, 'title': 'Nov naslov'}), {'embedding': None, 'embedding_digest': ''})
        self.assertEqual(embeddings.award_invalidation(None, data), {})

    def test_import_keeps_working_with_vectors(self):
        with patch('tenders.past_awards.normalize_notice', return_value=[
                {'id': 'a1', 'notice_id': '1', 'dossier_id': '', 'published_on': date(2025, 1, 5), 'data': {'title': 'Servis'}}]):
            import_notices([{}])
            PastAward.objects.filter(pk='a1').update(embedding=[0.5] * embeddings.DIMENSIONS,
                embedding_digest=embeddings.digest(embeddings.award_text({'title': 'Servis'})))
            import_notices([{}])
        self.assertIsNotNone(PastAward.objects.get(pk='a1').embedding)
