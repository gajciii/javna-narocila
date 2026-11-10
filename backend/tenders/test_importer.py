from unittest.mock import MagicMock, patch
import json

from django.test import TestCase
from .importer import import_notice, normalize_payload, parse_notice_id
from .models import SyncAttempt, Tender, TenderVersion, Notification
from .seed import ensure_seed


class ImporterTests(TestCase):
    def setUp(self):
        ensure_seed()

    def response(self, status=200, payload=None):
        response = MagicMock()
        response.status_code = status
        response.iter_content.return_value = [json.dumps(payload or {}).encode()]
        response.__enter__.return_value = response
        return response

    def payload(self, **extra):
        return {"title": "Preizkusna spletna platforma", "summary": "Razvoj spletne platforme in integracija podatkov.", "buyer": "Testni naročnik", "status": "open", "kind": "services", "deadline": "2099-12-12T12:00:00+01:00", "cpv": ["72262000-9"], **extra}

    def test_source_id_accepts_known_forms(self):
        for value in ["1144799", "https://www.enarocanje.si/#/pregled-objav/1144799?d=1", "https://www.enarocanje.si/api/obrazec/objava/obrazecGet?id=1144799"]:
            self.assertEqual(parse_notice_id(value), "1144799")

    def test_source_url_blocks_untrusted_destinations(self):
        for value in ["http://127.0.0.1/1144799", "https://enarocanje.si.evil.test/?id=1144799", "https://user:secret@enarocanje.si/#/pregled-objav/1144799", "https://enarocanje.si:8080/#/pregled-objav/1144799", "https://example.com/#/pregled-objav/1144799", True]:
            with self.assertRaises(ValueError):
                parse_notice_id(value)

    @patch("tenders.importer.requests.get")
    def test_network_failure_returns_labeled_known_snapshot(self, get):
        get.return_value = self.response(407)
        result = import_notice("1144799")
        self.assertEqual(result["mode"], "snapshot")
        self.assertEqual(result["tender"].pk, "ijs-archive")
        self.assertIn("HTTP 407", result["warning"])
        self.assertFalse(SyncAttempt.objects.get().success)
        self.assertEqual(Tender.objects.count(), 7)

    @patch("tenders.importer.requests.get")
    def test_failure_for_unknown_notice_does_not_fabricate_record(self, get):
        get.return_value = self.response(404)
        result = import_notice("9999999")
        self.assertEqual(result["mode"], "unavailable")
        self.assertNotIn("tender", result)
        self.assertEqual(Tender.objects.count(), 7)

    @patch("tenders.importer.requests.get")
    def test_unknown_schema_is_saved_but_not_normalized(self, get):
        raw = {"unrecognized": {"anything": "value"}}
        get.return_value = self.response(payload=raw)
        result = import_notice("9999999")
        self.assertEqual(result["mode"], "unavailable")
        self.assertEqual(SyncAttempt.objects.get().raw, raw)
        self.assertEqual(Tender.objects.count(), 7)

    @patch("tenders.importer.requests.get")
    def test_daily_sync_limit_counts_failed_attempts(self, get):
        get.return_value = self.response(407)
        import_notice("1144799")
        import_notice("1144799")
        result = import_notice("1144799")
        self.assertEqual(get.call_count, 2)
        self.assertIn("dveh", result["warning"])

    @patch("tenders.importer.requests.get")
    def test_valid_metadata_idempotent_and_unknown_dates_preserved(self, get):
        get.return_value = self.response(payload=self.payload())
        result = import_notice("9999999")
        again = import_notice("9999999")
        self.assertEqual(result["mode"], "live")
        record = again["tender"]
        self.assertIsNone(record.data["published_at"])
        self.assertEqual(record.data["cpv"], ["72262000"])
        self.assertEqual(TenderVersion.objects.filter(tender=record).count(), 1)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertEqual(Notification.objects.filter(tender=record, type="new").count(), 1)

    def test_unknown_status_and_missing_deadline_not_assumed_open(self):
        self.assertIsNone(normalize_payload(self.payload(status=None), "9999999"))
        self.assertIsNone(normalize_payload(self.payload(deadline=None), "9999999"))
        self.assertIsNone(normalize_payload(self.payload(kind=None), "9999999"))

    @patch("tenders.importer.requests.get")
    def test_known_archive_uses_existing_identity(self, get):
        get.return_value = self.response(payload=self.payload(status="cancelled"))
        result = import_notice("1144799")
        self.assertEqual(result["tender"].id, "ijs-archive")
        self.assertEqual(Tender.objects.count(), 7)
        self.assertFalse(Notification.objects.filter(tender=result["tender"], type="new").exists())

    @patch("tenders.importer.requests.get")
    def test_followed_update_notifies_even_when_closed(self, get):
        get.return_value = self.response(payload=self.payload())
        record = import_notice("9999999")["tender"]
        record.following = True
        record.save()
        get.return_value = self.response(payload=self.payload(status="cancelled"))
        updated = import_notice("9999999")["tender"]
        self.assertEqual(updated.data["version"], 2)
        self.assertTrue(updated.data["has_update"])
        self.assertEqual(Notification.objects.filter(tender=record, type="correction").count(), 1)

    @patch("tenders.importer.requests.get")
    def test_previous_real_import_available_during_outage(self, get):
        get.return_value = self.response(payload=self.payload())
        record = import_notice("9999999")["tender"]
        get.return_value = self.response(503)
        result = import_notice("9999999")
        self.assertEqual(result["mode"], "snapshot")
        self.assertEqual(result["tender"].pk, record.pk)
