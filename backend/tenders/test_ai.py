"""Grounding/fallback boundary tests; no network or real API key is used."""
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase

from .ai import chat, analyze_document
from .models import Document
from .seed import ensure_seed, get_profile
from .services import all_tenders


@patch.dict("os.environ", {"OPENAI_API_KEY": "test-never-sent"})
class GroundingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def citation(self):
        doc = Document.objects.get(pk="energy-v1")
        req = doc.extraction["requirements"][0]
        return {"tender_id": "energy-iot", "title": "Model-generated label", "document_id": doc.id, "page": req["page"], "quote": req["quote"]}

    @patch("tenders.ai.structured_call")
    def test_valid_evidence_is_accepted_and_title_comes_from_database(self, call):
        call.return_value = {"answer": "Razpis zahteva primerljivo referenco.", "citations": [self.citation()]}
        result = chat("Kakšen je referenčni pogoj?", all_tenders(), get_profile(), ["energy-iot"])
        self.assertEqual(result["mode"], "live")
        self.assertIn("IoT", result["citations"][0]["title"])

    @patch("tenders.ai.structured_call")
    def test_fabricated_quote_is_rejected_with_explicit_demo_fallback(self, call):
        evidence = {**self.citation(), "quote": "Vsi ponudniki samodejno izpolnjujejo pogoje."}
        call.return_value = {"answer": "Vsi pogoji so izpolnjeni.", "citations": [evidence]}
        result = chat("Pojasni pogoje", all_tenders(), get_profile(), ["energy-iot"])
        self.assertEqual(result["mode"], "demo")
        self.assertIn("warning", result)
        self.assertNotEqual(result["citations"][0]["quote"], evidence["quote"])

    @patch("tenders.ai.structured_call")
    def test_document_from_different_tender_is_rejected(self, call):
        call.return_value = {"answer": "Primerjava", "citations": [{**self.citation(), "tender_id": "sport-portal"}]}
        result = chat("Primerjaj", all_tenders(), get_profile(), ["energy-iot", "sport-portal"])
        self.assertEqual(result["mode"], "demo")

    @patch("tenders.ai.structured_call")
    def test_empty_citations_not_presented_as_grounded_answer(self, call):
        call.return_value = {"answer": "Zagotovo boste izbrani.", "citations": []}
        result = chat("Kateri razpis priporočaš?", all_tenders(), get_profile())
        self.assertEqual(result["mode"], "demo")
        self.assertNotIn("Zagotovo", result["answer"])

    @patch("tenders.ai.structured_call", side_effect=TimeoutError)
    def test_provider_outage_keeps_application_usable(self, call):
        result = chat("Katere reference manjkajo?", all_tenders(), get_profile(), ["sport-portal"])
        self.assertEqual(result["mode"], "demo")
        self.assertIn("Manjka", result["answer"])
        self.assertIn("warning", result)

    @patch("tenders.ai.structured_call")
    def test_invalid_extraction_never_overwrites_known_evidence(self, call):
        doc = Document.objects.get(pk="energy-v1")
        original = deepcopy(doc.extraction)
        bad = deepcopy(original)
        bad["requirements"][0]["page"] = 300
        call.return_value = bad
        result = analyze_document(doc)
        self.assertEqual(result["mode"], "demo")
        doc.refresh_from_db()
        self.assertEqual(doc.extraction, original)

    @patch("tenders.ai.structured_call")
    def test_null_threshold_never_overwrites_valid_conditions(self, call):
        doc = Document.objects.get(pk="energy-v1")
        original = deepcopy(doc.extraction)
        bad = deepcopy(original)
        bad["requirements"][0]["minimum"] = None
        call.return_value = bad
        result = analyze_document(doc)
        self.assertEqual(result["mode"], "demo")
        doc.refresh_from_db()
        self.assertEqual(doc.extraction, original)
