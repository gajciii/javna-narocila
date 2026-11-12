"""Grounding/fallback boundary tests; no network or real API key is used."""
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase

from .ai import chat, analyze_document
from .models import Document
from .seed import ensure_seed, get_profile
from .services import all_tenders


@patch.dict("os.environ", {"OPENAI_API_KEY": "test-never-sent", "OPENROUTER_API_KEY": ""})
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
    def test_quote_joined_with_ellipsis_is_accepted_only_if_every_part_is_verbatim(self, call):
        doc = Document.objects.get(pk="energy-v1")
        reqs = [r for r in doc.extraction["requirements"] if r["page"] == doc.extraction["requirements"][0]["page"]]
        joined = {**self.citation(), "quote": f"{reqs[0]['quote']} [...] {reqs[-1]['quote']}"}
        call.return_value = {"answer": "Pogoja.", "citations": [joined]}
        self.assertEqual(chat("Pogoji?", all_tenders(), get_profile(), ["energy-iot"])["mode"], "live")
        forged = {**self.citation(), "quote": f"{reqs[0]['quote']} [...] Vsi ponudniki samodejno izpolnjujejo pogoje."}
        call.return_value = {"answer": "Pogoja.", "citations": [forged]}
        self.assertEqual(chat("Pogoji?", all_tenders(), get_profile(), ["energy-iot"])["mode"], "demo")

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


class OpenRouterProviderTests(TestCase):
    schema = {"type": "object", "additionalProperties": False, "properties": {"answer": {"type": "string"}}, "required": ["answer"]}

    def fake_client(self, content):
        from types import SimpleNamespace
        message = SimpleNamespace(content=content)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=None)))
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])
        client.chat.completions.create = create
        return client, calls

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-test-never-sent", "OPENAI_API_KEY": "also-set"})
    def test_openrouter_uses_chat_completions_with_strict_schema(self):
        from .ai import provider, structured_call
        client, calls = self.fake_client('```json\n{"answer": "ok"}\n```')
        with patch("openai.OpenAI", return_value=client) as ctor:
            self.assertEqual(provider(), "openrouter")
            self.assertEqual(structured_call(self.schema, "Navodilo", {"q": 1}), {"answer": "ok"})
        self.assertEqual(ctor.call_args.kwargs["base_url"], "https://openrouter.ai/api/v1")
        sent = calls[0]
        self.assertEqual(sent["response_format"]["json_schema"]["schema"], self.schema)
        self.assertTrue(sent["extra_body"]["provider"]["require_parameters"])
        self.assertIn("nezaupanja", sent["messages"][0]["content"])

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-test-never-sent", "OPENAI_API_KEY": ""})
    def test_openrouter_invalid_json_shape_is_rejected(self):
        from jsonschema import ValidationError
        from .ai import structured_call
        client, _ = self.fake_client('{"wrong": 1}')
        with patch("openai.OpenAI", return_value=client), self.assertRaises(ValidationError):
            structured_call(self.schema, "Navodilo", {})
