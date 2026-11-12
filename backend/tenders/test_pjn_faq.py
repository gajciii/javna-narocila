import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tenders.document_index import search_passages
from tenders.documents import active_documents
from tenders.models import Document, PipelineJob, Tender, TenderQuestion
from tenders.pipeline_jobs import index_identity
from tenders.pjn_faq import parse_item, sync_faq, tender_faq

DOSSIER = 'obrazec/objava/dosjeObrazecGetList?idDosje=7'
FIRST = 'obrazecFaq/obrazecFaqGetList?idObrazec=10'
CURRENT = 'obrazecFaq/obrazecFaqGetList?idObrazec=20'
QUESTION = {'id': 1, 'idObrazec': 10, 'idSifObrazecFaqTip': 2, 'datumVnosa': '2026-11-01T10:00:00',
            'tekst': 'VPRAŠANJE\nAli so referenčna dela lahko izvedena kot podizvajalec?\nODGOVOR\nDa, referenca podizvajalca se upošteva.'}
CLARIFICATION = {'id': 2, 'idObrazec': 20, 'idSifObrazecFaqTip': 3, 'datumVnosa': '2026-11-05T09:00:00',
                 'tekst': 'Naročnik podaljšuje rok za oddajo ponudb.'}


def portal(first=(QUESTION,), current=(CLARIFICATION,)):
    responses = {DOSSIER: [{'idObrazec': 20, 'objavaDejanskaDatum': '2026-11-04'},
                           {'idObrazec': 10, 'objavaDejanskaDatum': '2026-10-29'}],
                 FIRST: list(first), CURRENT: list(current)}
    return patch('tenders.pjn_faq.fetch_json', side_effect=responses.__getitem__)


class ParseTests(TestCase):
    def test_splits_question_and_answer(self):
        item = parse_item({'id': 1, 'idSifObrazecFaqTip': 2, 'tekst': 'VPRAŠANJE\nAli je dopusten <b>enakovreden</b> lovilec?\n\nODGOVOR\nDa &amp; z dokazili.\n\n'})
        self.assertEqual((item['kind'], item['question'], item['answer']), ('question', 'Ali je dopusten enakovreden lovilec?', 'Da & z dokazili.'))

    def test_unanswered_question_and_clarification(self):
        self.assertEqual(parse_item({'id': 2, 'idSifObrazecFaqTip': 2, 'tekst': 'VPRAŠANJE\nRok?'})['answer'], '')
        clarification = parse_item({'id': 3, 'idSifObrazecFaqTip': 3, 'tekst': 'Naročnik podaljšuje rok.'})
        self.assertEqual((clarification['kind'], clarification['question']), ('clarification', 'Naročnik podaljšuje rok.'))


class SyncTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        media = override_settings(MEDIA_ROOT=Path(self.tmp.name), PIPELINE_S3_ENDPOINT='')
        media.enable()
        self.addCleanup(media.disable)
        self.tender = Tender.objects.create(id='pjn-dosje-7', data={
            'source_type': 'real', 'title': 'Ureditev površin', 'status': 'open', 'deadline': '2099-01-01T10:00:00+01:00',
            'version': 1, 'source_url': 'https://www.enarocanje.si/#/pregled-objav/20',
            'source_metadata': {'dossier_id': 7, 'notice_id': '20'}})

    def test_sync_stores_questions_and_indexes_them_as_a_document(self):
        before = index_identity(self.tender)
        with portal():
            result = sync_faq(self.tender)
        self.assertEqual((result['count'], result['changed']), (2, True))
        self.assertEqual(TenderQuestion.objects.filter(tender=self.tender).count(), 2)
        self.tender.refresh_from_db()
        self.assertNotEqual(index_identity(self.tender), before)
        document = Document.objects.get(pk='faq-pjn-dosje-7')
        self.assertIn(document, active_documents(self.tender))
        self.assertEqual(document.status, 'processed')
        self.assertTrue(document.indexed_content_id)
        found, _ = search_passages([document], {}, terms=['podizvajal'])
        self.assertEqual(len(found), 1)
        self.assertIn('Da, referenca podizvajalca se upošteva.', found[0]['quote'])
        self.assertTrue(found[0]['locator'].startswith('Vprašanje 1'))

    def test_unchanged_answers_keep_identity_and_removed_items_are_deleted(self):
        with portal():
            sync_faq(self.tender)
        self.tender.refresh_from_db()
        identity = index_identity(self.tender)
        with portal():
            self.assertFalse(sync_faq(self.tender)['changed'])
        self.tender.refresh_from_db()
        self.assertEqual(index_identity(self.tender), identity)
        with portal(current=()):
            self.assertTrue(sync_faq(self.tender)['changed'])
        self.assertEqual(list(TenderQuestion.objects.values_list('source_id', flat=True)), [1])

    def test_no_questions_keeps_original_identity(self):
        identity = index_identity(self.tender)
        with portal(first=(), current=()):
            sync_faq(self.tender)
        self.tender.refresh_from_db()
        self.assertEqual(index_identity(self.tender), identity)
        self.assertFalse(Document.objects.filter(pk='faq-pjn-dosje-7').exists())

    @override_settings(PIPELINE_REMOTE=True)
    def test_view_serves_stored_rows_and_requeues_indexing_on_change(self):
        with portal():
            response = APIClient().get('/api/tenders/pjn-dosje-7/faq')
        self.assertEqual([i['id'] for i in response.data['items']], [2, 1])
        self.assertEqual(response.data['document_id'], 'faq-pjn-dosje-7')
        self.assertTrue(PipelineJob.objects.filter(tender=self.tender, kind='index').exists())
        with patch('tenders.pjn_faq.fetch_json') as fetch:
            self.assertEqual(len(APIClient().get('/api/tenders/pjn-dosje-7/faq').data['items']), 2)
        fetch.assert_not_called()  # Fresh copy is read from the database.

    def test_portal_error_falls_back_to_stored_copy(self):
        with portal():
            sync_faq(self.tender)
        self.tender.refresh_from_db()
        self.tender.data['source_metadata']['faq_synced_at'] = '2020-01-01T00:00:00+00:00'
        self.tender.save()
        with patch('tenders.pjn_faq.fetch_json', side_effect=ValueError('Portal ni vrnil veljavnega JSON odziva.')):
            data = tender_faq(self.tender)
        self.assertEqual(len(data['items']), 2)
        self.assertIn('warning', data)

    def test_demo_tender_is_not_fetched(self):
        demo = Tender.objects.create(id='demo-faq', data={'source_type': 'demo'})
        with patch('tenders.pjn_faq.fetch_json') as fetch:
            self.assertFalse(tender_faq(demo)['available'])
        fetch.assert_not_called()
