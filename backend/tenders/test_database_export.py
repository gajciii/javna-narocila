import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings

from .database_export import database_archive
from .models import Document, PipelineRun, Tender


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DatabaseExportTests(TestCase):
    url = '/api/admin/pipeline/database-export'

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user('export-admin', password='private-password', is_staff=True)
        cls.member = get_user_model().objects.create_user('export-member')
        cls.tender = Tender.objects.create(pk='export-test', data={'title': 'Občina Škofja Loka'})
        cls.document = Document.objects.create(pk='export-doc', tender=cls.tender, title='Dokument',
                                               path='s3://razpizi-documents/sha256/example')
        cls.pipeline_run = PipelineRun.objects.create(source='manual', mode='existing', requested_by=cls.admin)

    def download(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = b''.join(response.streaming_content)
        return response, content

    def test_export_requires_active_staff_session(self):
        with patch('tenders.database_export.database_archive') as archive:
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.client.force_login(self.member)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.admin.is_active = False
            self.admin.save(update_fields=['is_active'])
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            archive.assert_not_called()

    def test_download_is_portable_fixture_without_authentication_data(self):
        self.client.force_login(self.admin)
        self.assertTrue(Session.objects.exists())
        response, content = self.download()
        self.assertEqual(response['Content-Type'], 'application/gzip')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('.json.gz', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        records = json.loads(gzip.decompress(content))
        self.assertTrue(all(row['model'].startswith('tenders.') for row in records))
        tender = next(row for row in records if row['model'] == 'tenders.tender' and row['pk'] == self.tender.pk)
        self.assertEqual(tender['fields']['data']['title'], 'Občina Škofja Loka')
        run = next(row for row in records if row['model'] == 'tenders.pipelinerun' and row['pk'] == self.pipeline_run.pk)
        self.assertIsNone(run['fields']['requested_by'])
        self.assertNotIn(self.admin.password, gzip.decompress(content).decode())
        self.pipeline_run.refresh_from_db()
        self.assertEqual(self.pipeline_run.requested_by_id, self.admin.pk)

    def test_export_can_be_loaded_with_django_loaddata(self):
        self.client.force_login(self.admin)
        _, content = self.download()
        tender_id, document_id, run_id = self.tender.pk, self.document.pk, self.pipeline_run.pk
        self.pipeline_run.delete()
        self.document.delete()
        self.tender.delete()
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / 'export.json.gz'
            fixture.write_bytes(content)
            call_command('loaddata', str(fixture), verbosity=0)
        tender = Tender.objects.get(pk=tender_id)
        self.assertEqual(tender.data['title'], 'Občina Škofja Loka')
        self.assertEqual(Document.objects.get(pk=document_id).tender_id, tender.pk)
        self.assertIsNone(PipelineRun.objects.get(pk=run_id).requested_by_id)

    def test_failures_do_not_expose_server_details(self):
        self.client.force_login(self.admin)
        with patch('tenders.database_export.database_archive', side_effect=OSError('private-server-path')):
            with self.assertLogs('tenders.pipeline_admin', level='ERROR'):
                response = self.client.get(self.url)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-server-path', response.content.decode())

    def test_serialization_failure_closes_temporary_file(self):
        with TemporaryFile(mode='w+b') as archive:
            with patch('tenders.database_export.TemporaryFile', return_value=archive):
                with patch('tenders.database_export.ApplicationSerializer.serialize', side_effect=ValueError('broken')):
                    with self.assertRaises(ValueError):
                        database_archive()
            self.assertTrue(archive.closed)


class ArchiveTransactionTests(TransactionTestCase):
    def test_archive_uses_its_own_transaction_and_remains_readable_after_commit(self):
        Tender.objects.create(pk='snapshot-test', data={'title': 'Snapshot'})
        with database_archive() as archive:
            records = json.loads(gzip.decompress(archive.read()))
        self.assertTrue(any(row['model'] == 'tenders.tender' and row['pk'] == 'snapshot-test'
                            for row in records))
