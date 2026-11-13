import io
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from .models import Document, Tender
from .submission_review import MAX_FILE, read_uploads, validate_checklist, validate_review

SOURCE = 'Ponudnik mora predloziti podpisan ponudbeni obrazec.'
BID = 'Ponudba st. 123: dobava opreme v vrednosti 80.000 EUR.'


def evidence(doc, quote):
    return {'document_id': doc, 'page': 1, 'quote': quote}


def documents(doc, text):
    return [{'id': doc, 'name': doc+'.pdf', 'pages': [{'page': 1, 'text': text}]}]


def requirement():
    return {'id': 'r1', 'title': 'Ponudbeni obrazec', 'requirement': SOURCE,
            'category': 'form', 'source': evidence('source', SOURCE)}


class SubmissionReviewTests(TestCase):
    def test_fabricated_source_cannot_create_requirement(self):
        with self.assertRaises(ValueError):
            validate_checklist({'requirements': [{**requirement(), 'source': evidence('source', 'Izmisljeno zavarovanje.')} ]}, documents('source', SOURCE))

    def test_covered_requires_actual_bid_evidence(self):
        row = {'requirement_id': 'r1', 'status': 'covered', 'explanation': 'ok', 'action': '', 'evidence': []}
        for proof in [[], [evidence('source', SOURCE)], [evidence('bid', 'Izmisljena ponudba.')]]:
            result = validate_review({'items': [{**row, 'evidence': proof}]}, [requirement()], documents('bid', BID), False)
            self.assertEqual(result[0]['status'], 'unknown')
        row['evidence'] = [evidence('bid', BID)]
        req = {**requirement(), 'requirement': 'Ponudbeni obrazec z navedenim zneskom.'}
        self.assertEqual(validate_review({'items': [row]}, [req], documents('bid', BID), False)[0]['status'], 'covered')
        self.assertEqual(validate_review({'items': [row]}, [requirement()], documents('bid', BID), False)[0]['status'], 'unknown')

    def test_incomplete_bid_never_confirms_absence(self):
        row = {'requirement_id': 'r1', 'status': 'missing', 'explanation': 'manjka', 'action': 'dopolni', 'evidence': []}
        self.assertEqual(validate_review({'items': [row]}, [requirement()], [], True)[0]['status'], 'unknown')
        self.assertEqual(validate_review({'items': [row]}, [requirement()], [], False)[0]['status'], 'missing')

    def test_missing_or_duplicate_result_rejected(self):
        with self.assertRaises(ValueError):
            validate_review({'items': []}, [requirement()], [], False)
        row = {'requirement_id': 'r1', 'status': 'unknown', 'explanation': '', 'action': '', 'evidence': []}
        with self.assertRaises(ValueError):
            validate_review({'items': [row, row]}, [requirement()], [], False)

    def test_zip_deduplicates_and_never_extracts_member_paths(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('../../outside.txt', BID)
            archive.writestr('copy.txt', BID)
            archive.writestr('__MACOSX/._copy.txt', 'ignored')
            archive.writestr('scan.bin', b'not a readable document')
        docs, issues, duplicates = read_uploads([SimpleUploadedFile('bid.zip', stream.getvalue())], 'bid')
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(docs[0]['pages'][0]['text'], BID)

    def test_bad_zip_and_oversized_archive_rejected(self):
        with self.assertRaises(ValidationError):
            read_uploads([SimpleUploadedFile('bad.zip', b'not zip')], 'bid')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for i in range(101): archive.writestr(f'{i}.txt', BID)
        with self.assertRaises(ValidationError):
            read_uploads([SimpleUploadedFile('many.zip', stream.getvalue())], 'bid')

    def test_upload_limit_is_50_mb(self):
        with self.assertRaises(ValidationError):
            read_uploads([SimpleNamespace(size=MAX_FILE + 1)], 'bid')

    @patch('tenders.submission_views.review', return_value={'result': 'covered'})
    @patch('tenders.submission_views.read_uploads', return_value=([], [], []))
    def test_multipart_upload_above_old_limit_reaches_review(self, read, review):
        Tender.objects.create(id='review-test', data={'version': 1})
        large_file = SimpleUploadedFile('large.pdf', b'%PDF-' + b'x' * (13 * 1024**2))
        response = APIClient().post('/api/tenders/review-test/submission-review',
                                    {'submission_files': large_file}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(review.call_count, 1)

    def test_alternative_bid_folders_are_never_combined(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('PDF/form.txt', BID)
            archive.writestr('PDF/BREZ/form.txt', 'Druga razlicica prijave, brez dokazila o referenci.')
        with self.assertRaises(ValidationError):
            read_uploads([SimpleUploadedFile('bid.zip', stream.getvalue())], 'bid')
        docs, _, _ = read_uploads([SimpleUploadedFile('bid.zip', stream.getvalue())], 'bid', folder='PDF')
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['pages'][0]['text'], BID)

    def test_review_accepts_only_bid_files(self):
        Tender.objects.create(id='review-test', data={'version': 1})
        response = APIClient().post('/api/tenders/review-test/submission-review', {
            'submission_files': SimpleUploadedFile('bid.txt', BID.encode()),
            'source_files': SimpleUploadedFile('source.txt', SOURCE.encode()),
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('zavihku Dokumenti', str(response.data))

    @patch('tenders.submission_review.provider', return_value='openrouter')
    @patch('tenders.submission_review.structured_call')
    def test_review_requires_stored_tender_documentation(self, call, provider):
        Tender.objects.create(id='review-test', data={'version': 1})
        response = APIClient().post('/api/tenders/review-test/submission-review', {
            'submission_files': SimpleUploadedFile('bid.txt', BID.encode()),
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('zavihku Dokumenti', str(response.data))
        call.assert_not_called()

    @patch('tenders.submission_review.provider', return_value='openrouter')
    @patch('tenders.submission_review.structured_call')
    def test_api_uses_separate_model_and_keeps_bid_out_of_sources(self, call, provider):
        tender = Tender.objects.create(id='review-test', data={'version': 1, 'title': 'Oprema'})
        Document.objects.create(id='source', tender=tender, title='Navodila.pdf', status='processed', path='not-used', pages=documents('source', SOURCE)[0]['pages'])
        call.side_effect = [
            {'requirements': [{k: v for k, v in requirement().items() if k != 'id'}]},
            {'items': [{'requirement_id': 'r1', 'status': 'covered', 'explanation': 'Dokaz je prisoten.', 'action': '', 'evidence': [evidence('bid-1', BID)]}]}]
        response = APIClient().post('/api/tenders/review-test/submission-review', {'submission_files': SimpleUploadedFile('prijava.txt', BID.encode())}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['counts']['unknown'], 1)
        self.assertEqual(response.data['model'], 'openai/gpt-6.1-terra')
        self.assertEqual(call.call_args_list[0].kwargs['model'], 'openai/gpt-6.1-terra')
        self.assertNotIn('submission_documents', call.call_args_list[0].args[2])
        self.assertEqual(Document.objects.count(), 1)

    @patch('tenders.submission_review.provider', return_value=None)
    def test_missing_key_does_not_return_fake_review(self, provider):
        Tender.objects.create(id='review-test', data={'version': 1})
        response = APIClient().post('/api/tenders/review-test/submission-review', {'submission_files': SimpleUploadedFile('bid.txt', BID.encode())}, format='multipart')
        self.assertEqual(response.status_code, 400)

    @patch('tenders.submission_review.provider', return_value='openrouter')
    @patch('tenders.submission_review.structured_call', side_effect=TimeoutError)
    def test_provider_failure_does_not_return_positive_result(self, call, provider):
        tender = Tender.objects.create(id='review-test', data={'version': 1})
        Document.objects.create(id='source', tender=tender, title='Navodila.pdf', status='processed', path='x', pages=documents('source', SOURCE)[0]['pages'])
        response = APIClient().post('/api/tenders/review-test/submission-review', {'submission_files': SimpleUploadedFile('bid.txt', BID.encode())}, format='multipart')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('items', response.data)
