from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from .models import Document, DocumentChunk, ErarPayment, IndexedContent, Tender
from .pipeline_admin import data_source_stats

BASE = '/api/admin/pipeline'


@override_settings(ACCOUNT_REQUIRE_LOGIN=False, HOSTED_REQUIRE_LOGIN=False, TEST_FIXTURE_DATA=False)
class DataSourceAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_user('data-admin', is_staff=True)
        self.member = get_user_model().objects.create_user('data-member')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.csrf = self.client.get(BASE + '/session').json()['csrf_token']
        self.tender = Tender.objects.create(pk='ocr-tender', data={'source_type': 'real', 'title': 'Pregled skenov'})

    def export(self, rows='one;1. 10. 2025;123,45;1111111000;2222222000;JN001234/2025\n'):
        return SimpleUploadedFile('export.csv', (
            'ID transakcije;Datum transakcije;Znesek EUR;Matična številka plačnika;Matična številka prejemnika;Številka JN\n'
            + rows).encode('utf-8'))

    def upload(self, file=None, exported_on='2025-10-02', csrf=True):
        return self.client.post(BASE + '/erar', {'file': file or self.export(), 'exported_on': exported_on},
                                HTTP_X_CSRFTOKEN=self.csrf if csrf else '')

    def test_read_and_upload_are_staff_only_and_upload_requires_csrf(self):
        self.assertEqual(self.upload(csrf=False).status_code, 403)
        for user in (None, self.member):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in ('/erar', '/documents'):
                self.assertEqual(self.client.get(BASE + url).status_code, 403)
            self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(ErarPayment.objects.count(), 0)

    def test_upload_is_idempotent_and_refreshes_stats_and_search(self):
        self.assertEqual(data_source_stats()['erar']['transactions'], 0)
        self.assertEqual(self.upload().status_code, 201)
        result = self.upload()
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()['imported'], 1)
        self.assertEqual(result.json()['erar']['transactions'], 1)
        self.assertEqual(ErarPayment.objects.get().amount, Decimal('123.45'))
        listing = self.client.get(BASE + '/erar', {'q': 'JN001234'}).json()
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['results'][0]['recipient'], '2222222000')
        self.assertEqual(self.client.get(BASE + '/erar', {'q': 'not-found'}).json()['count'], 0)

    def test_invalid_export_is_atomic_and_future_dates_are_rejected(self):
        invalid = self.export('one;1. 10. 2025;123,45;1111111000;2222222000;JN001234/2025\ntwo;bad-date;4;;;;\n')
        self.assertEqual(self.upload(invalid).status_code, 400)
        self.assertEqual(self.upload(exported_on='2099-10-01').status_code, 400)
        self.assertEqual(self.upload(SimpleUploadedFile('bad.csv', b'invalid-data')).status_code, 400)
        self.assertFalse(ErarPayment.objects.exists())

    def test_statistics_keep_currencies_separate_and_ignore_empty_identifiers(self):
        for pk, currency, amount in (('a', 'EUR', '123.45'), ('b', 'USD', '1000')):
            ErarPayment.objects.create(source_id=pk, paid_on=date(2025, 10, 1), amount=amount,
                currency=currency, recipient='2222222000' if pk == 'a' else '', exported_on=date(2025, 10, 2))
        stats = data_source_stats()['erar']
        self.assertEqual(stats['transactions'], 2)
        self.assertEqual(stats['recipients'], 1)
        self.assertEqual(stats['payers'], 0)
        self.assertEqual(Decimal(stats['eur_amount']), Decimal('123.45'))
        self.assertEqual(stats['other_currencies'], 1)

    def test_ocr_counts_pages_once_across_chunks_and_reused_documents(self):
        content = IndexedContent.objects.create(pk='ocr-content', sha256='a' * 64,
            extractor_version='test', format='pdf', pages=[{'page': 1, 'locator': 'stran 1 (OCR)', 'text': 'Prepoznano besedilo skenirane strani.'}])
        for ordinal, page in enumerate((1, 1, 2)):
            DocumentChunk.objects.create(content=content, ordinal=ordinal, page=page,
                locator=f'stran {page} (OCR)', text='Prepoznano besedilo', normalized_text='prepoznano besedilo')
        for pk in ('ocr-a', 'ocr-b'):
            Document.objects.create(pk=pk, tender=self.tender, title=f'{pk}.pdf', path='/missing.pdf',
                indexed_content=content, status='processed')
        Document.objects.create(pk='plain', tender=self.tender, title='Plain document', path='/missing.txt')
        Document.objects.create(pk='archive', tender=self.tender, title='Archive', path='/missing.zip', extraction={'mode': 'archive'})
        stats = data_source_stats()['ocr']
        self.assertEqual(stats, {'documents': 3, 'indexed': 2, 'ocr_documents': 2, 'ocr_contents': 1, 'ocr_pages': 2})
        listing = self.client.get(BASE + '/documents').json()
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['results'][0]['text_url'], '/api/documents/ocr-a/text')
        self.assertNotIn('Prepoznano besedilo', str(listing))
        preview = self.client.get(listing['results'][0]['text_url'])
        self.assertContains(preview, 'Prepoznano besedilo skenirane strani.')
        self.assertEqual(self.client.get(BASE + '/documents', {'ocr': '0'}).json()['count'], 3)
        self.assertEqual(self.client.get(BASE + '/documents', {'q': 'ocr-a'}).json()['count'], 1)

    def test_pagination_and_filters_are_bounded(self):
        for path in ('/erar?page=0', '/documents?page=-1', '/documents?ocr=anything'):
            self.assertEqual(self.client.get(BASE + path).status_code, 400)
        Document.objects.bulk_create([Document(id=f'page-{i:02}', tender=self.tender, title='Doc', path='/missing') for i in range(26)])
        first = self.client.get(BASE + '/documents?ocr=0').json()
        second = self.client.get(BASE + '/documents?ocr=0&page=2').json()
        self.assertEqual(first['count'], 26)
        self.assertEqual(len(first['results']), 25)
        self.assertEqual(len(second['results']), 1)
