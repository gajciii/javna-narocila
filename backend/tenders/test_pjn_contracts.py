import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from .document_index import index_document
from .keyword_expansion import document_keyword_hits
from .models import Tender
from .pipeline_download import download
from .pipeline_jobs import index_identity
from .pjn_contracts import sync_contracts

URL = 'https://www.enarocanje.si/api/datoteka/get?id=contract'


class ContractTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(pk='pjn-dosje-contract', data={
            'source_type': 'real', 'version': 1, 'status': 'closed',
            'source_metadata': {'dossier_id': 624029, 'attachment_url': None}})
        self.forms = [{'idPogodba': 508904, 'idObrazecStatus': 100,
                       'objavaIdent': 'JN004399/2026-POG/01'}]
        self.contract = {'id': 508904, 'idDosje': 624029,
                         'datoteka': [{'url': URL, 'ime': 'Pogodba.txt'}]}

    @patch('tenders.pjn_contracts.fetch_json')
    def test_contract_only_tender_is_downloaded_indexed_and_searchable(self, fetch):
        fetch.side_effect = [self.forms + self.forms, self.contract]
        before = index_identity(self.tender)
        sync_contracts(self.tender)
        self.assertNotEqual(before, index_identity(self.tender))
        self.assertEqual(fetch.call_count, 2)
        payload = 'Podpisnik ANICA UŽMAH. TRR SI56 0400 1005 0442 608.'.encode()
        def download_source(url, path):
            self.assertEqual(url, URL)
            path.write_bytes(payload)
            return hashlib.sha256(payload).hexdigest(), 'Pogodba.txt'
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=Path(tmp), PIPELINE_S3_ENDPOINT=''), \
                patch('tenders.pipeline_download.fetch_file', side_effect=download_source) as transfer:
            download(self.tender)
            doc = self.tender.document_records.get()
            index_document(doc)
            download(self.tender)
            transfer.assert_called_once()
            for term in ['ANICA UŽMAH', 'SI56 0400 1005 0442 608']:
                evidence = next(iter(document_keyword_hits([term], [self.tender.pk])[self.tender.pk].values()))
                self.assertEqual(evidence['document_id'], doc.pk)
                self.assertIn(term, evidence['quote'])
            self.assertEqual(doc.extraction['notice_number'], 'JN004399/2026-POG/01')
            fetch.side_effect = [[]]
            sync_contracts(self.tender)
            self.assertEqual(document_keyword_hits(['ANICA UŽMAH'], [self.tender.pk]), {})

    @patch('tenders.pjn_contracts.fetch_json')
    def test_invalid_or_failed_responses_preserve_manifest(self, fetch):
        fetch.side_effect = [self.forms, self.contract]
        sync_contracts(self.tender)
        stored = self.tender.data['source_metadata'].copy()
        for contract in [{**self.contract, 'idDosje': 99},
                         {**self.contract, 'datoteka': [{'url': 'https://example.com/private.pdf'}]}]:
            fetch.side_effect = [self.forms, contract]
            with self.assertRaises(ValueError):
                sync_contracts(self.tender)
            self.tender.refresh_from_db()
            self.assertEqual(self.tender.data['source_metadata'], stored)

    @patch('tenders.pjn_contracts.fetch_json')
    def test_only_published_contracts_and_addenda_are_collected(self, fetch):
        fetch.side_effect = [self.forms + [{'idPogodba': 8, 'idObrazecStatus': 1},
            {'idPogodba': None, 'idObrazecStatus': 100},
            {'idPogodba': 9, 'idObrazecStatus': 100, 'objavaIdent': 'JN004399/2026-DOD/01'}],
            self.contract, {'id': 9, 'idDosje': 624029, 'datoteka': [{'url': URL + '2', 'ime': 'Dodatek.pdf'}]}]
        self.assertEqual(len(sync_contracts(self.tender)), 2)
        first = index_identity(self.tender)
        fetch.side_effect = [self.forms, self.contract]
        sync_contracts(self.tender)
        self.assertNotEqual(first, index_identity(self.tender))
