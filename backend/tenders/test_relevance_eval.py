"""Relevance comparison harness; no network or real API key is used."""
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from .models import Tender
from .relevance_eval import (EVAL_PROFILES, LABELS, RUBRIC, export_rows, gemini_request, metrics, predict_gemini,
                             predict_llm, read_rows, run, write_rows)
from .seed import ensure_seed


def row(profile_id='lumina', tender_id='t1', label='', **extra):
    return {'profile_id': profile_id, 'tender_id': tender_id, 'label': label, 'note': '', 'profile': '',
            'title': extra.get('title', 'Razvoj spletne platforme'), 'kind': extra.get('kind', 'services'),
            'cpv': '72000000', 'topics': 'Storitve IT', 'summary': extra.get('summary', 'Razvoj in vzdrževanje portala.')}


class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def test_only_real_tenders_and_existing_labels_survive_reexport(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'labels.csv'
            rows = export_rows(Tender.objects.order_by('pk'), path)
            self.assertTrue(rows)
            self.assertEqual({r['tender_id'] for r in rows}, {t.pk for t in Tender.objects.all() if t.data.get('source_type') == 'real'})
            self.assertEqual(len(rows), len(EVAL_PROFILES) * len({r['tender_id'] for r in rows}))
            rows[0]['label'], rows[0]['note'] = 'p', 'jedrna dejavnost'
            rows.append(row('optika', 'gone-from-db', 'n'))
            write_rows(path, rows)
            again = {(r['profile_id'], r['tender_id']): r for r in export_rows(Tender.objects.all(), path)}
            first = again[(rows[0]['profile_id'], rows[0]['tender_id'])]
            self.assertEqual((first['label'], first['note']), ('primeren', 'jedrna dejavnost'))
            self.assertEqual(again[('optika', 'gone-from-db')]['label'], 'neprimeren')

    def test_unknown_label_is_rejected_with_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'labels.csv'
            write_rows(path, [row(label='mogoče')])
            with self.assertRaisesRegex(ValueError, 'Vrstica 2'):
                read_rows(path)


class MetricTests(TestCase):
    def test_accuracy_fit_precision_and_severe_errors(self):
        rows = [row(tender_id='a', label='primeren'), row(tender_id='b', label='neprimeren'),
                row(tender_id='c', label='delno'), row(tender_id='d', label='neprimeren'), row(tender_id='e')]
        preds = {('lumina', 'a'): {'label': 'primeren'}, ('lumina', 'b'): {'label': 'primeren'},
                 ('lumina', 'c'): {'label': 'delno'}, ('lumina', 'd'): {'label': 'neprimeren'}}
        m = metrics(rows, preds)
        self.assertEqual((m['labelled'], m['predicted']), (4, 4))
        self.assertAlmostEqual(m['accuracy'], 0.75)
        self.assertAlmostEqual(m['fit_precision'], 0.5)
        self.assertAlmostEqual(m['fit_recall'], 1.0)
        self.assertEqual(m['severe_errors'], 1)
        self.assertNotIn('brier', m)

    def test_brier_only_for_probabilistic_predictions(self):
        m = metrics([row(label='primeren')], {('lumina', 't1'): {'label': 'primeren', 'probabilities': [0.0, 0.0, 1.0]}})
        self.assertEqual(m['brier'], 0.0)


@patch.dict('os.environ', {'OPENAI_API_KEY': '', 'OPENROUTER_API_KEY': ''})
class ApproachTests(TestCase):
    def test_providers_without_keys_are_skipped_and_rules_always_run(self):
        results = run([row(label='primeren')], ['rules', 'llm', 'gemini'], gemini_key=None)
        self.assertIn('metrics', results['rules'])
        self.assertIn('skipped', results['llm'])
        self.assertIn('skipped', results['gemini'])

    @patch('tenders.ai.structured_call')
    def test_llm_answers_for_unknown_tenders_are_ignored(self, call):
        call.return_value = {'answers': [{'tender_id': 't1', 'label': 'primeren'}, {'tender_id': 'invented', 'label': 'primeren'}]}
        self.assertEqual(predict_llm([row()]), {('lumina', 't1'): {'label': 'primeren'}})
        payload = call.call_args.args[2]
        self.assertNotIn('Primerna ulica', str(payload))  # fictional eval profile, not the stored company profile

    def test_gemini_request_uses_shared_profile_input_and_score_rubric(self):
        body = gemini_request('lumina', [row(), row(tender_id='t2')], 'gemini-decision-1')
        self.assertEqual(body['model'], 'models/gemini-decision-1')
        self.assertIn('Lumina', body['input'])
        self.assertEqual(set(body['questions']), {'q0', 'q1'})
        self.assertEqual(body['questions']['q0']['type'], 'score')
        self.assertEqual(body['questions']['q0']['criteria'], RUBRIC)
        self.assertIn('Razvoj spletne platforme', body['questions']['q0']['instructions'])

    def test_gemini_question_ids_are_valid_for_any_tender_id(self):
        body = gemini_request('lumina', [row(tender_id='ocds-70d2nz-001cf86f:lot-1 ' + 'x' * 80)], 'gemini-decision-1')
        self.assertTrue(all(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', qid) for qid in body['questions']))

    @patch('tenders.relevance_eval.requests.post')
    def test_gemini_answer_maps_most_probable_level(self, post):
        post.return_value = MagicMock(status_code=200, json=lambda: {'answers': {'q7': {}, 'q0': {
            'type': 'score', 'score': 1.3, 'confidence': 0.6, 'probabilities': {'0': 0.1, '1': 0.6, '2': 0.3}}}})
        result = predict_gemini([row()], 'test-never-sent', 'gemini-decision-1')
        self.assertEqual(result[('lumina', 't1')]['label'], LABELS[1])
        self.assertEqual(result[('lumina', 't1')]['probabilities'], [0.1, 0.6, 0.3])
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'test-never-sent')

    @patch('tenders.relevance_eval.requests.post')
    def test_gemini_error_never_echoes_key_or_body(self, post):
        post.return_value = MagicMock(status_code=403, text='{"error": "key test-never-sent invalid"}')
        with self.assertRaises(RuntimeError) as ctx:
            predict_gemini([row()], 'test-never-sent', 'gemini-decision-1')
        self.assertNotIn('test-never-sent', str(ctx.exception))
