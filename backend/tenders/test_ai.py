"""Grounding/fallback boundary tests; no network or real API key is used."""
from copy import deepcopy
from unittest.mock import patch

from django.test import TestCase

from .ai import analyze_document
from .models import Document
from .seed import ensure_seed


@patch.dict("os.environ", {"OPENAI_API_KEY": "test-never-sent", "OPENROUTER_API_KEY": ""})
class GroundingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

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
