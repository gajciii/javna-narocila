import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.conf import settings
from .importer import import_notice, normalize_payload, parse_notice_id
from .pjn_sync import persist_notice, sync_recent, reserve_run
from .pjn_normalize import normalize_notice
from .pjn_documents import download_documents
from .pjn_transport import fetch
from .documents import active_documents
from .models import SyncAttempt, SyncRun, Tender, TenderVersion, Notification
from .seed import ensure_seed, get_profile
from .matching import content_match, serialize_tender

FIXTURES = Path(__file__).parent / 'fixtures'


class ImporterTests(TestCase):
    def setUp(self):
        ensure_seed()
        media = TemporaryDirectory(prefix='radar-import-tests-')
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=Path(media.name)))

    def response(self, status=200, payload=None, headers=None):
        response = MagicMock()
        response.status_code = status
        response.headers = headers or {}
        response.iter_content.return_value = [json.dumps(payload or {}).encode()]
        response.__enter__.return_value = response
        return response

    def payload(self, **extra):
        raw = json.loads((FIXTURES / 'pjn-notice.json').read_text(encoding='utf-8'))
        raw.update(id=9999999, idDosje=999999, naslov='Preizkusna spletna platforma',
                   kratekOpis='Razvoj spletne platforme in integracija podatkov.',
                   idSifCpv=8093, datumDoPonudba='2099-12-12T12:00:00', razpisnaDokumentacijaURL=None)
        raw.update(extra)
        return raw

    def test_verified_wire_schema_and_codelists(self):
        raw = json.loads((FIXTURES / 'pjn-notice.json').read_text(encoding='utf-8'))
        data = normalize_notice(raw, '1229976')
        self.assertEqual(data['buyer'], 'ZDRAVSTVENI DOM MURSKA SOBOTA')
        self.assertEqual(data['region'], 'Pomurska')
        self.assertEqual(data['kind'], 'services')
        self.assertEqual(data['value'], 86000)
        self.assertRegex(data['cpv'][0], r'^\d{8}$')
        self.assertEqual(data['source_metadata']['notice_number'], 'JN008907/2026-SL1/01')
        self.assertTrue(data['deadline'].endswith('+01:00'))
        self.assertIsNone(data['criteria'][0]['weight'])

    def test_broad_cpv_does_not_make_cybersecurity_a_high_software_match(self):
        raw = json.loads((FIXTURES / 'pjn-notice.json').read_text(encoding='utf-8'))
        data = normalize_notice(raw, '1229976')
        level, score, reasons = content_match(data, get_profile())
        self.assertEqual(level, 'medium')
        self.assertLess(score, 70)
        self.assertIn('CPV', reasons[0])

    def test_actual_software_subject_can_match_despite_broad_cpv(self):
        data = normalize_notice(self.payload(), '9999999')
        self.assertEqual(content_match(data, get_profile())[0], 'high')

    def test_construction_with_website_link_not_recommended_to_software_company(self):
        data = normalize_notice(self.payload(idSifNarociloVrsta=3, naslov='Ureditev športnega parka',
            kratekOpis='Izgradnja tribun. Dokumentacija je na spletni strani občine.'), '9999999')
        self.assertEqual(content_match(data, get_profile())[0], 'low')

    def test_unknown_source_status_is_not_claimed_closed(self):
        record, _, _ = persist_notice(normalize_notice(self.payload(datumDoPonudba=None), '9999999'))
        data = serialize_tender(record, get_profile())
        self.assertEqual(data['status'], 'unconfirmed')
        self.assertEqual(data['match']['recommendation'], 'review')
        self.assertIn('nista potrjena', data['match']['open_question'])
        self.assertFalse(Notification.objects.filter(tender=record, type='new').exists())

    def test_source_id_accepts_known_forms(self):
        for value in ['1144799', 'https://www.enarocanje.si/#/pregled-objav/1144799?d=1', 'https://enarocanje.si/api/obrazec/objava/obrazecGet?id=1144799']:
            self.assertEqual(parse_notice_id(value), '1144799')

    def test_source_url_blocks_untrusted_destinations(self):
        for value in ['http://127.0.0.1/1144799', 'https://enarocanje.si.evil.test/?id=1144799', 'https://user:secret@enarocanje.si/#/pregled-objav/1144799', 'https://enarocanje.si:8080/#/pregled-objav/1144799', True]:
            with self.assertRaises(ValueError):
                parse_notice_id(value)

    @patch('tenders.pjn_transport.requests.get')
    def test_network_failure_returns_labeled_snapshot(self, get):
        get.return_value = self.response(407)
        result = import_notice('1144799')
        self.assertEqual(result['mode'], 'snapshot')
        self.assertIn('HTTP 407', result['warning'])
        self.assertFalse(SyncAttempt.objects.get().success)

    @patch('tenders.pjn_transport.requests.get')
    def test_unknown_schema_saved_without_fabricated_record(self, get):
        get.return_value = self.response(payload={'unknown': 'field'})
        result = import_notice('9999999')
        self.assertEqual(result['mode'], 'unavailable')
        self.assertEqual(SyncAttempt.objects.get().raw, {'unknown': 'field'})
        self.assertEqual(Tender.objects.count(), 7)

    @patch('tenders.pjn_transport.requests.get')
    def test_daily_limit_includes_failed_runs(self, get):
        get.return_value = self.response(407)
        import_notice('1144799'); import_notice('1144799')
        third = import_notice('1144799')
        self.assertEqual(get.call_count, 2)
        self.assertIn('dveh', third['warning'])
        self.assertEqual(SyncRun.objects.count(), 2)

    @patch('tenders.pjn_transport.requests.get')
    def test_verified_metadata_idempotent(self, get):
        get.return_value = self.response(payload=self.payload())
        first = import_notice('9999999')
        second = import_notice('9999999')
        self.assertEqual(first['mode'], 'live')
        self.assertEqual(first['tender'].id, 'pjn-dosje-999999')
        self.assertEqual(TenderVersion.objects.filter(tender=second['tender']).count(), 1)
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], 'RazpIzi/0.2')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_unconfirmed_or_result_not_open(self):
        self.assertEqual(normalize_notice(self.payload(datumDoPonudba=None), '9999999')['status'], 'unconfirmed')
        self.assertEqual(normalize_notice(self.payload(idSifPostopekFaza=1), '9999999')['status'], 'closed')
        self.assertEqual(normalize_notice(self.payload(idSifPostopekFaza=6), '9999999')['status'], 'unconfirmed')
        self.assertIsNone(normalize_payload(self.payload(idSifNarociloVrsta=9000), '9999999'))

    def test_id_mismatch_and_foreign_currency(self):
        with self.assertRaises(ValueError):
            normalize_notice(self.payload(), '111')
        self.assertIsNone(normalize_notice(self.payload(idSifValutaOcenjenaBrezDDV=4), '9999999')['value'])

    def test_correction_uses_same_dossier_and_notifies_once(self):
        original = self.payload(id=111, objavaDejanskaDatum='2026-11-01T10:00:00')
        record, _, _ = persist_notice(normalize_notice(original, '111'))
        record.following = True; record.save()
        changed = self.payload(id=222, objavaDejanskaDatum='2026-11-10T10:00:00', datumDoPonudba='2099-12-20T10:00:00', idObrazecPrejPopravek=111)
        updated, created, modified = persist_notice(normalize_notice(changed, '222'))
        persist_notice(normalize_notice(changed, '222'))
        self.assertFalse(created); self.assertTrue(modified)
        self.assertEqual(record.pk, updated.pk)
        self.assertEqual(updated.data['version'], 2)
        self.assertEqual(Notification.objects.filter(tender=record, type='deadline').count(), 1)
        stale, _, modified = persist_notice(normalize_notice(original, '111'))
        self.assertFalse(modified)
        self.assertEqual(stale.data['version'], 2)

    def test_followed_award_notifies_even_when_ineligible(self):
        record, _, _ = persist_notice(normalize_notice(self.payload(), '9999999'))
        record.following = True; record.save()
        data = self.payload(id=9999998, idSifPostopekFaza=1, objavaDejanskaDatum='2099-12-30T12:00:00')
        updated, _, _ = persist_notice(normalize_notice(data, '9999998'))
        self.assertEqual(updated.data['status'], 'closed')
        self.assertEqual(Notification.objects.filter(tender=record, type='correction').count(), 1)

    @patch('tenders.pjn_transport.requests.get')
    def test_redirect_to_untrusted_host_blocked(self, get):
        get.return_value = self.response(302, headers={'Location': 'http://127.0.0.1/private'})
        with self.assertRaises(ValueError):
            fetch('obrazec/objava/obrazecGet?id=123')
        self.assertEqual(get.call_count, 1)

    @patch('tenders.pjn_sync.download_documents', return_value={'downloaded': 0})
    @patch('tenders.pjn_sync.fetch_json')
    def test_bulk_run_counts_as_one_slot_and_deduplicates_dossier(self, fetch_json, download):
        fetch_json.side_effect = [{'data': [{'idObrazec': 9999999, 'idDosje': 999999}, {'idObrazec': 9999998, 'idDosje': 999999}]}, self.payload()]
        result = sync_recent(20)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['checked'], 1)
        self.assertEqual(SyncRun.objects.count(), 1)
        self.assertTrue(SyncRun.objects.get().finished_at)

    @patch('tenders.pjn_documents.fetch')
    def test_actual_pdf_and_safe_zip_processing(self, fetch_file):
        record, _, _ = persist_notice(normalize_notice(self.payload(razpisnaDokumentacijaURL='https://www.enarocanje.si/api/datoteka/get?id=public'), '9999999'))
        pdf = (settings.DEMO_DOCUMENTS_ROOT / 'energy-v1.pdf').read_bytes()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../../outside.pdf', pdf)
            z.writestr('obrazec.docx', b'unsupported file')
        fetch_file.return_value = (archive.getvalue(), {'Content-Disposition': 'attachment; filename="dokumenti.zip"'})
        outcome = download_documents(record)
        self.assertEqual(outcome['downloaded'], 3)
        docs = list(record.document_records.all())
        self.assertTrue(any(d.pages for d in docs))
        self.assertTrue(any(d.status == 'unprocessed' for d in docs))
        self.assertTrue(all(Path(d.path).resolve().is_relative_to(settings.MEDIA_ROOT.resolve()) for d in docs))
        download_documents(record)
        self.assertEqual(record.document_records.count(), 3)
        record.data['version'] = 2; record.save()
        self.assertEqual(active_documents(record), [])

    def test_demo_reset_preserves_real_imports(self):
        record, _, _ = persist_notice(normalize_notice(self.payload(), '9999999'))
        ensure_seed(reset=True)
        self.assertTrue(Tender.objects.filter(pk=record.pk).exists())

    def test_prefill_name_without_selection_never_returns_fake_company(self):
        response = self.client.post('/api/profile/prefill', {'query': 'Resnično podjetje'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('profile', response.json())
