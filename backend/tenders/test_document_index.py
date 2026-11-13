import hashlib
import io
import tempfile
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from threading import Barrier, Thread

from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .document_index import chunks, index_document, search_passages
from .models import Document, DocumentChunk, IndexedContent, PipelineJob, Tender
from .pipeline_download import copy_stream
from .pipeline_jobs import claim, enqueue_assessment, enqueue_index, execute, finish

PROFILE = {'activity': 'Montaža klimatskih naprav', 'description': '', 'expertise': [],
           'keywords': ['hlajenje'], 'technologies': []}


@override_settings(PIPELINE_REMOTE=True, PIPELINE_S3_ENDPOINT='')
@patch.dict('os.environ', {'GEMINI_API_KEY': ''})
class IndexTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'popis.txt'
        self.path.write_text('Dobava in montaža klimatskih naprav v novi osnovni šoli.\n'
                             'Izvedba prezračevanja in hlajenja prostorov.')
        self.tender = Tender.objects.create(id='index-test', data={'version': 1, 'title': 'Gradnja šole'})
        self.doc = Document.objects.create(id='upload-index-test', tender=self.tender, title='popis.txt',
            path=str(self.path), sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_extraction_and_chunks_are_shared_between_companies_and_documents(self):
        index_document(self.doc)
        other = Document.objects.create(id='copy-index-test', tender=self.tender, title='copy.txt',
            path=str(self.path), sha256=self.doc.sha256)
        with patch('tenders.document_index.extract_document', side_effect=AssertionError('Must reuse content')):
            index_document(other)
        self.assertEqual(other.indexed_content_id, self.doc.indexed_content_id)
        self.assertEqual(IndexedContent.objects.count(), 1)
        found, overflow = search_passages([self.doc], PROFILE)
        self.assertEqual(len(found), 1)
        self.assertIn('klimatskih', found[0]['quote'])
        self.assertEqual(found[0]['locator'], 'txt, del 1')
        self.assertIsNone(found[0]['page'])
        self.assertEqual(search_passages([self.doc], {**PROFILE, 'activity': 'Tiskanje brošur', 'keywords': []}), ([], 0))

    def test_chunks_are_exact_substrings_with_page_locations(self):
        text = 'Postavka montaža klimatske naprave. ' * 300
        result = list(chunks([{'page': 7, 'text': text}]))
        self.assertGreater(len(result), 1)
        self.assertTrue(all(page == 7 and quote in text and len(quote) <= 1800 for page, _, quote in result))

    def test_durable_queue_indexes_once_then_assesses_without_reextracting(self):
        request = enqueue_assessment(self.tender, PROFILE)
        self.assertEqual(enqueue_assessment(self.tender, PROFILE).pk, request.pk)
        job = claim()
        self.assertEqual(job.kind, 'index')
        execute(job)
        job.refresh_from_db()
        self.assertEqual(job.state, 'complete')
        with patch('tenders.document_index.extract_document', side_effect=AssertionError('Already indexed')):
            job = claim()
            self.assertEqual(job.kind, 'assess')
            execute(job)
        job.refresh_from_db()
        self.assertEqual(job.state, 'complete')
        self.assertEqual(len(job.result['findings']), 1)
        self.assertEqual(job.result['findings'][0]['mode'], 'text_candidate')
        # A new profile reuses the completed global indexing job.
        other = enqueue_assessment(self.tender, {**PROFILE, 'activity': 'Prezračevanje'})
        self.assertNotEqual(other.pk, job.pk)
        self.assertEqual(PipelineJob.objects.filter(kind='index').count(), 1)

    def test_remote_post_only_enqueues_work_and_get_returns_progress(self):
        with patch('tenders.opportunities.get_profile', return_value=PROFILE), \
             patch('tenders.opportunities.process_document', side_effect=AssertionError('Web must not extract')):
            response = self.client.post(f'/api/tenders/{self.tender.pk}/attachment-opportunities')
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.json()['pending'])
            while job := claim():
                execute(job)
            response = self.client.get(f'/api/tenders/{self.tender.pk}/attachment-opportunities')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['analysed'])
            self.assertFalse(response.json()['pending'])
            self.assertEqual(len(response.json()['findings']), 1)

    def test_expired_lease_is_recovered_and_old_worker_cannot_finish(self):
        enqueue_index(self.tender)
        first = claim()
        PipelineJob.objects.filter(pk=first.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        second = claim()
        self.assertNotEqual(first.lease, second.lease)
        self.assertFalse(finish(first, {'stale': True}))
        self.assertTrue(finish(second, {'fresh': True}))

    def test_new_version_invalidates_pending_work(self):
        enqueue_index(self.tender)
        job = claim()
        self.tender.data['version'] = 2
        self.tender.save()
        execute(job)
        job.refresh_from_db()
        self.assertEqual(job.state, 'superseded')
        self.assertFalse(DocumentChunk.objects.exists())

    def test_blocked_assessments_cannot_starve_indexing_and_interactive_work_has_priority(self):
        enqueue_index(self.tender)  # Old background work.
        interactive = Tender.objects.create(pk='interactive', data={'version': 1})
        request = enqueue_assessment(interactive, PROFILE)
        dependency_id = request.payload['index_job']
        PipelineJob.objects.bulk_create([PipelineJob(key=f'blocked-{i}', tender=interactive,
            version=1, kind='assess', payload={'index_job': dependency_id}, available_at=timezone.now())
            for i in range(35)])
        self.assertEqual(claim().pk, dependency_id)

    def test_failed_dependency_is_visible_and_can_be_retried(self):
        job = enqueue_assessment(self.tender, PROFILE)
        PipelineJob.objects.filter(pk=job.payload['index_job']).update(state='failed', error='Failed download')
        self.assertIsNone(claim())
        job.refresh_from_db()
        self.assertEqual(job.state, 'failed')
        enqueue_assessment(self.tender, PROFILE)
        self.assertEqual(claim().kind, 'index')

    def test_large_transfer_copies_in_chunks_and_stops_at_limit(self):
        destination = Path(self.tmp.name) / 'download'
        with patch('tenders.pipeline_download.shutil.disk_usage') as usage:
            usage.return_value.free = 10**12
            self.assertEqual(copy_stream([b'first', b'second'], destination, 11),
                             hashlib.sha256(b'firstsecond').hexdigest())
            with self.assertRaises(ValueError):
                copy_stream([b'first', b'second'], destination, 10)

    def test_pdf_parser_limit_does_not_abort_other_documents(self):
        from pypdf.errors import LimitReachedError
        Document.objects.create(id='upload-other', tender=self.tender, title='other.txt', path=str(self.path))
        enqueue_index(self.tender)
        job = claim()
        with patch('tenders.pipeline_jobs.index_document', side_effect=[LimitReachedError('PDF limit'), None]) as index:
            execute(job)
        job.refresh_from_db()
        self.assertEqual(index.call_count, 2)
        self.assertEqual(job.state, 'complete')
        self.assertEqual(job.result['unreadable_count'], 1)

    def test_tender_list_uses_bulk_metadata_without_loading_document_text(self):
        from .services import all_tenders
        self.doc.pages = [{'page': 1, 'text': 'Large document text'}]
        self.doc.save()
        # Tenders, document metadata and the account's ignored tenders.
        with self.assertNumQueries(3):
            tenders = all_tenders(PROFILE)
        self.assertEqual(tenders[0]['documents'][0]['pages'], 1)
        from .documents import document_metadata
        metadata = document_metadata().get(pk=self.doc.pk)
        self.assertIn('pages', metadata.get_deferred_fields())

    def test_archive_is_streamed_and_member_names_cannot_escape_scratch(self):
        from .pipeline_download import download
        self.tender.data['source_metadata'] = {'attachment_url': 'https://www.enarocanje.si/api/datoteka/get?id=1'}
        self.tender.save()

        def fetch(url, path):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('../../escaped.txt', 'Dobava klimatskih naprav za osnovno šolo.')
            return hashlib.sha256(path.read_bytes()).hexdigest(), 'popis.zip'
        with override_settings(MEDIA_ROOT=Path(self.tmp.name)), patch('tenders.pipeline_download.fetch_file', side_effect=fetch):
            download(self.tender)
            downloaded = self.tender.document_records.filter(id__startswith='index-doc-')
            self.assertEqual(downloaded.count(), 2)
            member = downloaded.get(title='escaped.txt')
            self.assertEqual(Path(member.path).parent, Path(self.tmp.name) / 'indexed')
            self.assertFalse((Path(self.tmp.name) / 'escaped.txt').exists())
            self.tender.refresh_from_db()
            download(self.tender)
            self.assertEqual(downloaded.count(), 2)

    def test_archive_expansion_budget_stops_before_member_is_written(self):
        from .pipeline_download import download
        self.tender.data['source_metadata'] = {'attachment_url': 'https://www.enarocanje.si/api/datoteka/get?id=1'}
        self.tender.save()
        def fetch(url, path):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('large.txt', 'x' * 1000)
            return hashlib.sha256(path.read_bytes()).hexdigest(), 'popis.zip'
        with override_settings(MEDIA_ROOT=Path(self.tmp.name), PIPELINE_MAX_EXPANDED=100), \
                patch('tenders.pipeline_download.fetch_file', side_effect=fetch):
            with self.assertRaises(ValueError):
                download(self.tender)
        self.assertFalse(self.tender.document_records.filter(title='large.txt').exists())
        self.assertEqual(self.tender.document_records.get(title='popis.zip').status, 'unprocessed')


class PostgresConcurrencyTests(TransactionTestCase):
    def test_two_workers_do_not_claim_same_job(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL row locking')
        tender = Tender.objects.create(pk='concurrency-test', data={'version': 1})
        PipelineJob.objects.create(key='queue-test', tender=tender, version=1, kind='index', available_at=timezone.now())
        barrier, claimed = Barrier(2), []

        def worker():
            close_old_connections()
            try:
                barrier.wait()
                result = claim()
                claimed.append(result.pk if result else None)
            finally:
                connection.close()
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(claimed), 2)
        self.assertEqual(sum(pk is not None for pk in claimed), 1)
