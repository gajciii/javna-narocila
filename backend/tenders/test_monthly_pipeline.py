"""Offline verification of monthly pagination, attachment evidence and resumable output."""
import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from .deep_extract import extract_document
from .deep_relevance import analyse, candidate_passages, decision_scores, document_fingerprint, historical_winners
from .models import Document, MonthlyScanItem, PastAward, Tender
from .monthly_pipeline import grid_rows, profile_fingerprint, scan_notice, write_report


HVAC = {'activity': 'Dobava in montaža klimatskih naprav', 'description': 'Vgrajujemo klime in hladilne sisteme.',
        'expertise': ['klimatske naprave'], 'keywords': ['klime', 'hlajenje'], 'technologies': []}


class AttachmentOpportunityViewTests(TestCase):
    def test_archived_and_interactive_results_require_current_profile_and_evidence(self):
        tender = Tender.objects.create(id='pjn-test', data={'title': 'Priprava dogodka', 'version': 1,
                                      'source_metadata': {'notice_id': '123'}})
        doc = Document.objects.create(id='pjn-doc-test', tender=tender, title='Popis.pdf', path='unused',
            status='processed', pages=[{'page': 2, 'text': 'Izvajalec poskrbi za tiskanje brošur za obiskovalce.'}])
        profile = {'activity': 'Tiskanje brošur'}
        finding = analyse(tender, [doc], profile)['findings'][0]
        MonthlyScanItem.objects.create(tender=tender, period='2026-11', notice_id='123', state='complete',
            fingerprint=profile_fingerprint(profile, '', 'gemini-decision-1', False),
            result={'version': 1, 'documents_fingerprint': document_fingerprint([doc]), 'findings': [finding]})
        url = '/api/tenders/pjn-test/attachment-opportunities'
        with patch('tenders.opportunities.get_profile', return_value=profile) as active_profile, \
             patch('tenders.opportunities.gemini_settings', return_value=(None, 'gemini-decision-1')):
            self.assertEqual(self.client.get(url).json()['findings'][0]['page'], 2)
            active_profile.return_value = {'activity': 'Izposoja vozil'}
            self.assertFalse(self.client.get(url).json()['analysed'])
            self.assertEqual(self.client.post(url).json()['findings'], [])
            self.assertTrue(self.client.get(url).json()['analysed'])
            doc.pages[0]['text'] = 'Izposoja vozil je del razpisane storitve.'
            doc.save(update_fields=['pages'])
            self.assertFalse(self.client.get(url).json()['analysed'])
            self.assertEqual(self.client.post(url).json()['findings'][0]['document_url'], '/api/documents/pjn-doc-test')


class PaginationTests(TestCase):
    @patch('tenders.monthly_pipeline.fetch_json')
    def test_all_pages_keep_only_november_and_unique_notices(self, fetch):
        fetch.side_effect = [
            {'lastRow': 3, 'data': [
                {'idObrazec': 1, 'objavaDejanskaDatum': '2026-11-02T10:00:00'},
                {'idObrazec': 2, 'objavaDejanskaDatum': '2026-11-03T10:00:00'}]},
            {'lastRow': 3, 'data': [
                {'idObrazec': 3, 'objavaDejanskaDatum': '2026-11-04T10:00:00'}]},
        ]
        self.assertEqual(list(grid_rows('2026-11')), ['1', '2', '3'])
        self.assertEqual(fetch.call_args_list[1].args[1]['startRow'], 2)
        self.assertEqual(fetch.call_args_list[0].args[1]['objavaDejanskaDatumDo'], '2026-12-01T00:00:00')

    @patch('tenders.monthly_pipeline.fetch_json')
    def test_missing_middle_page_fails_instead_of_claiming_completeness(self, fetch):
        fetch.return_value = {'lastRow': 5, 'data': []}
        with self.assertRaises(ValueError):
            list(grid_rows('2026-11'))


class DeepAttachmentTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(pk='test-construction', data={
            'title': 'Gradnja šole', 'summary': 'Gradbena dela', 'source_type': 'real', 'status': 'open',
            'version': 1, 'source_url': 'https://www.enarocanje.si/#/pregled-objav/123',
            'source_metadata': {'notice_id': '123', 'attachment_url': 'https://www.enarocanje.si/api/datoteka/get?id=1'}})

    def test_docx_and_xlsx_are_read_without_fictional_pdf_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / 'spec.docx'
            with zipfile.ZipFile(docx, 'w') as archive:
                archive.writestr('word/document.xml', '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Dobava klimatskih naprav</w:t></w:r></w:p></w:body></w:document>')
            pages, kind = extract_document(docx, 'spec.docx')
            self.assertEqual(kind, 'docx')
            self.assertIn('klimatskih', pages[0]['text'])
            self.assertIn('document.xml', pages[0]['locator'])

            xlsx = Path(tmp) / 'popis.xlsx'
            with zipfile.ZipFile(xlsx, 'w') as archive:
                archive.writestr('xl/sharedStrings.xml', '<sst><si><t>Klimatska naprava</t></si></sst>')
                archive.writestr('xl/worksheets/sheet1.xml', '<worksheet><sheetData><row><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>')
            pages, kind = extract_document(xlsx, 'popis.xlsx')
            self.assertEqual(kind, 'xlsx')
            self.assertIn('Klimatska naprava', pages[0]['text'])
            self.assertIn('sheet1.xml', pages[0]['locator'])

    @patch('tenders.deep_relevance.requests.post')
    def test_decision_one_receives_only_capabilities_and_cited_public_excerpt(self, post):
        post.return_value = MagicMock(status_code=200, json=lambda: {'answers': {'q0': {
            'probabilities': {'0': 0.05, '1': 0.9, '2': 0.05}}}})
        profile = {**HVAC, 'name': 'Zasebno podjetje', 'registration_number': '1234567'}
        passage = {'quote': 'Dobava in montaža klimatskih naprav za novo šolo.'}
        scores = decision_scores([passage], profile, self.tender, 'test-never-sent', 'gemini-decision-1')
        self.assertEqual(scores[0]['partial'], 0.9)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], 'models/gemini-decision-1')
        self.assertNotIn('Zasebno podjetje', str(body))
        self.assertNotIn('1234567', str(body))
        self.assertIn(passage['quote'], body['questions']['q0']['instructions'])

    def test_contacts_are_published_winners_of_prior_awards(self):
        PastAward.objects.create(pk='pjn-111-1', notice_id='111', dossier_id='111', published_on=date(2025, 5, 1),
            data={'title': 'Dobava klimatskih naprav', 'lot_title': '',
                  'description': 'Dobava in montaža klimatskih naprav za šole.', 'cpv': [], 'kind': 'goods',
                  'awarded': True, 'winners': [{'name': 'Klima Primer d.o.o.', 'registration_number': '1234567000'}]})
        contacts = historical_winners(self.tender, 'Dobava in montaža klimatskih naprav za šole.')
        self.assertEqual(contacts[0]['historical_role'], 'winner')
        self.assertEqual(contacts[0]['name'], 'Klima Primer d.o.o.')
        self.assertEqual(contacts[0]['past_notice_url'], 'https://www.enarocanje.si/#/pregled-objav/111')

    @patch('tenders.deep_relevance.historical_winners', return_value=[])
    @patch('tenders.deep_relevance.decision_scores')
    @patch('tenders.deep_relevance.gemini_settings', return_value=('test-never-sent', 'gemini-decision-1'))
    def test_hidden_climate_work_is_found_in_construction_attachment(self, _settings, decisions, _winners):
        doc = Document.objects.create(pk='spec', tender=self.tender, title='Tehnične specifikacije.pdf', path='unused',
            status='processed', version=1, pages=[
                {'page': 1, 'text': 'Projekt obsega gradnjo nove šole in ureditev okolice.'},
                {'page': 2, 'text': 'Strojne instalacije vključujejo dobavo in montažo klimatskih naprav v učilnicah.'}],
            extraction={'mode': 'unprocessed'})
        passages, _ = candidate_passages([doc], HVAC)
        self.assertTrue(any(p['page'] == 2 and 'klimatskih' in p['quote'] for p in passages))
        decisions.return_value = [{'unsuitable': 0.05, 'partial': 0.9, 'suitable': 0.05}] * len(passages)
        result = analyse(self.tender, [doc], HVAC, ai_budget=10)
        self.assertEqual(result['findings'][0]['kind'], 'supplier_or_subcontractor')
        self.assertEqual(result['findings'][0]['document_id'], 'spec')
        self.assertEqual(result['findings'][0]['page'], 2)

    @patch('tenders.monthly_pipeline.download_documents', return_value={'downloaded': 1})
    @patch('tenders.monthly_pipeline.collect_notice')
    def test_scan_records_unreadable_attachment_as_partial(self, collect, _download):
        collect.return_value = {'mode': 'live', 'tender': self.tender}
        Document.objects.create(pk='legacy-doc', tender=self.tender, title='Popis.xls', path='unused',
                                status='unprocessed', version=1, error='Format ni podprt.', extraction={'mode': 'unprocessed'})
        item = scan_notice('2026-11', '123', HVAC, 'fingerprint', '', 0)
        self.assertEqual(item.state, 'partial')
        self.assertEqual(item.result['unresolved_documents'][0]['title'], 'Popis.xls')
        self.assertEqual(item.result['findings'], [])

    @patch('tenders.monthly_pipeline.download_documents')
    @patch('tenders.monthly_pipeline.collect_notice')
    def test_older_notice_never_inherits_newer_attachment_evidence(self, collect, download):
        self.tender.data['source_metadata']['notice_id'] = '124'
        self.tender.save(update_fields=['data'])
        collect.return_value = {'mode': 'live', 'tender': self.tender}
        item = scan_notice('2026-11', '123', HVAC, 'fingerprint', '', 0)
        self.assertEqual(item.state, 'superseded')
        self.assertEqual(item.result['superseded_by'], '124')
        download.assert_not_called()

    def test_report_marks_superseded_notice_and_incomplete_month(self):
        MonthlyScanItem.objects.create(period='2026-11', notice_id='122', tender=self.tender,
            state='complete', result={'notice_id': '122', 'title': '=SUM(1,1)', 'findings': [{
                'kind': 'supplier_or_subcontractor', 'confidence': 0.9, 'document_title': 'Spec.pdf',
                'locator': 'stran 2', 'quote': 'Klimatske naprave', 'historical_winners': []}]})
        with tempfile.TemporaryDirectory() as tmp:
            report = write_report('2026-11', Path(tmp) / 'report.json', 1, True)
            self.assertTrue(report['notices'][0]['superseded'])
            self.assertTrue(report['limited_run'])
            self.assertEqual(json.loads((Path(tmp) / 'report.json').read_text(encoding='utf-8'))['scanned_count'], 1)
            self.assertIn("'=SUM(1,1)", (Path(tmp) / 'report.csv').read_text(encoding='utf-8-sig'))
