import hashlib
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from . import embeddings
from .document_index import index_document, search_passages
from .models import Document, DocumentChunk, IndexedContent, Tender
from .ocr_import import import_results
from .ocr_policy import OCR_IMPORT_VERSION


class OfflineOCRImportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.digest = 'a' * 64
        self.source = 's3://documents/sha256/aa/' + self.digest
        self.tender = Tender.objects.create(pk='ocr-tender', data={})
        self.doc = Document.objects.create(pk='ocr-doc', tender=self.tender, title='Scan.pdf',
                                           path=self.source, sha256=self.digest, status='unprocessed')

    def result(self, **overrides):
        data = {'id': self.doc.pk, 'source': self.source, 'status': 'ocr', 'pages': [
            {'page': 1, 'text': 'Zahtevana referenca za montažo klimatskih naprav.', 'locator': 'stran 1 (OCR)'}]}
        data.update(overrides)
        (self.directory / (data['id'] + '.json')).write_text(json.dumps(data))

    def test_import_is_searchable_but_never_automatically_embedded(self):
        self.result()
        with patch('tenders.embeddings.embed', side_effect=AssertionError('API call forbidden')) as embed:
            report = import_results(self.directory, apply=True)
            self.doc.refresh_from_db()
            self.assertEqual(report['new_contents'], 1)
            self.assertEqual(self.doc.extraction['format'], 'pdf')
            self.assertEqual(self.doc.indexed_content.extractor_version, OCR_IMPORT_VERSION)
            passages, _ = search_passages([self.doc], {}, terms={'referenc'})
            self.assertEqual(passages[0]['page'], 1)
            self.assertEqual(embeddings.embed_chunks(), 0)
            self.assertEqual(embeddings.pending_counts()['chunks'], 0)
            embed.assert_not_called()

    def test_repeat_is_noop_and_normal_indexing_keeps_imported_text(self):
        self.result()
        import_results(self.directory, apply=True)
        self.doc.refresh_from_db()
        identity = self.doc.indexed_content_id
        report = import_results(self.directory, apply=True)
        self.assertEqual(report['new_chunks'], 0)
        self.assertEqual(report['documents_updated'], 0)
        with patch('tenders.document_index.local_file', side_effect=AssertionError('No PDF extraction')):
            index_document(self.doc)
        self.assertEqual(self.doc.indexed_content_id, identity)
        self.assertEqual(self.doc.extraction['index_version'], OCR_IMPORT_VERSION)

    def test_duplicate_records_share_content_and_unrelated_vectors_are_preserved(self):
        other = Document.objects.create(pk='duplicate', tender=self.tender, path=self.source,
                                        title='Same.pdf', sha256=self.digest)
        untouched = IndexedContent.objects.create(pk='untouched', sha256='b'*64,
            extractor_version='shared-v1', format='pdf', pages=[])
        chunk = DocumentChunk.objects.create(content=untouched, ordinal=0, page=1, locator='stran 1',
            text='Existing passage', normalized_text='existing passage', embedding=[0.5]*1024)
        self.result()
        report = import_results(self.directory, apply=True)
        self.doc.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(report['documents_updated'], 2)
        self.assertEqual(other.indexed_content_id, self.doc.indexed_content_id)
        chunk.refresh_from_db()
        self.assertIsNotNone(chunk.embedding)

    def test_dry_run_source_mismatch_and_bad_pages_do_not_write(self):
        self.result()
        report = import_results(self.directory)
        self.assertEqual(report['documents_updated'], 1)
        self.assertEqual(IndexedContent.objects.count(), 0)
        self.result(source='s3://documents/another-version')
        report = import_results(self.directory, apply=True)
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(IndexedContent.objects.count(), 0)
        self.result(pages=[{'page': -1, 'text': 'bad'}])
        report = import_results(self.directory, apply=True)
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(IndexedContent.objects.count(), 0)

    def test_partial_ocr_preserves_native_text_and_adds_only_missing_page(self):
        old_pages = [{'page': 1, 'text': 'Original native text must be preserved exactly.'},
                     {'page': 2, 'text': ''}, {'page': 3, 'text': ''}]
        old = IndexedContent.objects.create(pk='existing', sha256=self.digest, extractor_version='shared-v1',
                                           format='pdf', pages=old_pages)
        self.doc.indexed_content = old
        self.doc.pages = old_pages
        self.doc.save()
        self.result(pages=[{'page': 1, 'text': 'Worse OCR content must not replace native text.'},
                           {'page': 2, 'text': 'Additional readable text from a scanned page.'}])
        import_results(self.directory, apply=True)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.pages[0]['text'], old_pages[0]['text'])
        self.assertEqual(self.doc.pages[2]['text'], '')
        self.assertEqual(self.doc.extraction['ocr_import']['remaining_blank_pages'], 1)
        self.assertEqual(IndexedContent.objects.get(pk=old.pk).pages, old_pages)

    def test_readable_existing_index_is_not_rebuilt_from_worse_ocr(self):
        pages = [{'page': 1, 'text': 'Native PDF text with a complete and readable reference.'}]
        old = IndexedContent.objects.create(pk='existing', sha256=self.digest, extractor_version='shared-v1',
                                           format='pdf', pages=pages)
        self.doc.indexed_content = old
        self.doc.pages = pages
        self.doc.status = 'processed'
        self.doc.save()
        self.result(pages=[{'page': 1, 'text': 'OCR version that must not override good native text.'}])
        report = import_results(self.directory, apply=True)
        self.doc.refresh_from_db()
        self.assertEqual(report['new_contents'], 0)
        self.assertEqual(report['documents_updated'], 0)
        self.assertEqual(self.doc.indexed_content_id, old.pk)

    def test_native_pdf_parse_limit_is_reported_without_aborting_import(self):
        from pypdf.errors import LimitReachedError
        self.result(status='text_present', pages=[])
        with patch('tenders.pipeline_storage.local_file', return_value=nullcontext(self.directory / 'native.pdf')), \
                patch('tenders.documents.extract_pages', side_effect=LimitReachedError('Parse budget')):
            report = import_results(self.directory, apply=True)
        self.assertEqual(report['errors'][0]['error'], 'LimitReachedError')
        self.assertEqual(report['documents_updated'], 0)

    def test_pdf_control_glyphs_are_removed_before_database_insertion(self):
        self.result(pages=[{'page': 1, 'text': 'Referenca\x00 za montažo\x15 klimatskih naprav.\nDruga vrstica.'}])
        import_results(self.directory, apply=True)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.pages[0]['text'], 'Referenca za montažo klimatskih naprav.\nDruga vrstica.')
