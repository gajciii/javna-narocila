import io
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase

from . import embeddings
from .models import Document, DocumentChunk, IndexedContent, Tender
from .ocr_embeddings import embed_ocr_batch, ocr_chunks
from .ocr_policy import OCR_IMPORT_VERSION


class ScopedOCREmbeddingTests(TestCase):
    def setUp(self):
        embeddings._rejected[DocumentChunk].clear()
        self.addCleanup(embeddings._rejected[DocumentChunk].clear)
        self.tender = Tender.objects.create(id='ocr-embed-tender', data={})
        self.ocr = self.content('ocr', OCR_IMPORT_VERSION)
        self.old = self.content('old', 'shared-v1')

    def content(self, key, version, linked=True):
        content = IndexedContent.objects.create(pk=key, sha256=key*8,
            extractor_version=version, pages=[], format='pdf')
        if linked:
            Document.objects.create(pk='doc-'+key, tender=self.tender, title=key+'.pdf', indexed_content=content)
        return content

    def chunk(self, content, text, ordinal=0, vector=None):
        return DocumentChunk.objects.create(content=content, ordinal=ordinal, page=1, locator='stran 1',
            text=text, normalized_text=text, embedding=vector)

    def test_only_missing_current_ocr_vectors_are_billed_and_existing_vectors_are_kept(self):
        wanted = self.chunk(self.ocr, 'new OCR passage')
        existing = self.chunk(self.ocr, 'already embedded OCR', 1, [0.25]*1024)
        unrelated = self.chunk(self.old, 'unrelated missing passage')
        newer_version = self.content('future', 'ocr-local-v2')
        future = self.chunk(newer_version, 'not in this import')
        with patch('tenders.embeddings.embed', return_value=[[0.5]*1024]) as embed:
            self.assertEqual(embed_ocr_batch(), 1)
            self.assertEqual(embed_ocr_batch(), 0)
        embed.assert_called_once_with(['new OCR passage'])
        for row in (wanted, existing, unrelated, future):
            row.refresh_from_db()
        self.assertIsNotNone(wanted.embedding)
        self.assertAlmostEqual(float(existing.embedding.to_list()[0]), 0.25)
        self.assertIsNone(unrelated.embedding)
        self.assertIsNone(future.embedding)

    def test_snapshot_excludes_later_chunks_and_orphaned_old_contents(self):
        first = self.chunk(self.ocr, 'first OCR')
        later = self.chunk(self.ocr, 'later OCR', 1)
        orphan = self.content('orphan', OCR_IMPORT_VERSION, linked=False)
        self.chunk(orphan, 'unused OCR version')
        self.assertEqual(ocr_chunks().count(), 2)
        with patch('tenders.embeddings.embed', return_value=[[0.5]*1024]) as embed:
            self.assertEqual(embed_ocr_batch(maximum_pk=first.pk), 1)
        embed.assert_called_once_with(['first OCR'])
        later.refresh_from_db()
        self.assertIsNone(later.embedding)

    def test_status_never_calls_provider_and_repeated_paid_run_is_a_noop(self):
        self.chunk(self.ocr, 'already embedded', vector=[0.5]*1024)
        with patch('tenders.embeddings.embed', side_effect=AssertionError('No provider calls')), \
                patch('tenders.embeddings.enabled', return_value=True):
            call_command('embed_ocr_vectors', status=True, stdout=io.StringIO())
            call_command('embed_ocr_vectors', stdout=io.StringIO())


@skipUnless(connection.vendor == 'postgresql', 'Parallel locking requires PostgreSQL')
class ParallelOCREmbeddingTests(TransactionTestCase):
    def test_workers_do_not_bill_the_same_passage_twice(self):
        tender = Tender.objects.create(pk='parallel-ocr', data={})
        content = IndexedContent.objects.create(pk='parallel', sha256='c'*64,
            extractor_version=OCR_IMPORT_VERSION, pages=[], format='pdf')
        Document.objects.create(pk='parallel-doc', tender=tender, indexed_content=content)
        for i in range(5):
            DocumentChunk.objects.create(content=content, ordinal=i, page=1,
                locator='stran 1', text=f'OCR {i}', normalized_text=f'ocr {i}')
        with patch('tenders.embeddings.enabled', return_value=True), \
                patch('tenders.embeddings.embed', side_effect=lambda texts: [[0.5]*1024 for _ in texts]) as embed:
            call_command('embed_ocr_vectors', workers=2, batch_size=1, stdout=io.StringIO())
        billed = [text for call in embed.call_args_list for text in call.args[0]]
        self.assertEqual(len(billed), 5)
        self.assertEqual(len(set(billed)), 5)
        self.assertEqual(DocumentChunk.objects.filter(embedding__isnull=False).count(), 5)
