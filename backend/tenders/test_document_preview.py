from unittest.mock import patch

from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Document, IndexedContent, Tender


class DocumentPreviewTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username='preview-user'))
        self.seed = patch('tenders.views.ensure_seed').start()
        self.addCleanup(patch.stopall)
        tender = Tender.objects.create(id='preview-tender', data={})
        content = IndexedContent.objects.create(id='preview-content', sha256='a' * 64,
            extractor_version='test', format='docx', pages=[{
                'page': 1, 'locator': 'DOCX, del 1',
                'text': 'Zahtevani računalnik in RAČUNALNIK. <script>alert(1)</script>',
            }])
        self.doc = Document.objects.create(id='preview-doc', tender=tender,
            title='Dokument <img src=x onerror=alert(1)>.docx',
            path='s3://razpizi-documents/missing.docx', indexed_content=content)

    def test_missing_original_opens_indexed_text_and_legacy_hash_is_supported(self):
        error = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        with patch('tenders.pipeline_storage.stream', side_effect=error):
            response = self.client.get('/api/documents/preview-doc')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Izvirna datoteka ni na voljo v lokalni shrambi')
        self.assertContains(response, 'DOCX, del 1')
        self.assertContains(response, "params.has('search')")
        self.assertIn("default-src 'none'", response['Content-Security-Policy'])

    def test_search_highlights_all_matches_and_escapes_document_and_query(self):
        response = self.client.get('/api/documents/preview-doc/text', {'q': 'računalnik'})
        self.assertContains(response, '<mark>računalnik</mark>')
        self.assertContains(response, '<mark>RAČUNALNIK</mark>')
        self.assertContains(response, '2 zadetkov')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, '<img src=x')
        response = self.client.get('/api/documents/preview-doc/text', {'q': '"><img src=x onerror=alert(1)>'})
        self.assertNotContains(response, '<img src=x')

    def test_explicit_download_is_honest_about_missing_original(self):
        self.doc.path = '/missing/file.docx'
        self.doc.save()
        response = self.client.get('/api/documents/preview-doc?download=1')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['text_url'], '/api/documents/preview-doc/text')

    def test_missing_file_without_text_returns_404(self):
        self.doc.path = '/missing/file.docx'
        self.doc.indexed_content = None
        self.doc.save()
        self.assertEqual(self.client.get('/api/documents/preview-doc').status_code, 404)

    def test_available_pdf_still_streams_original_bytes(self):
        import io
        self.doc.title = 'dokument.pdf'
        self.doc.save()
        with patch('tenders.pipeline_storage.stream', return_value=io.BytesIO(b'%PDF-1.4\nexample')):
            response = self.client.get('/api/documents/preview-doc')
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
