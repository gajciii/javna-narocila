import json
import math
import os
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from .seed import ensure_seed, get_profile, today
from .services import all_tenders, trigger_event
from .models import Tender, Notification, CompanyProfile, Document, SavedSearch
from .matching import serialize_tender, evaluate_requirement
from .documents import evidence_valid, validated_extraction
from .filtering import apply_filters
from .validation import validate_profile
from .ai import demo_chat, chat


class RadarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def setUp(self):
        self.client = APIClient()
        # Uploaded fixtures must never accumulate in the developer's media folder.
        media = TemporaryDirectory(prefix='radar-tests-')
        self.addCleanup(media.cleanup)
        self.enterContext(self.settings(MEDIA_ROOT=Path(media.name)))

    def detail(self, id):
        return serialize_tender(Tender.objects.get(pk=id), get_profile())

    def test_bootstrap_and_seven_seed_records(self):
        response = self.client.get('/api/bootstrap')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['tenders']), 7)
        self.assertEqual(response.data['profile']['source'], 'demo')
        self.assertEqual(Document.objects.count(), 5)

    def test_demo_documents_are_actually_extracted_and_evidence_matches(self):
        for doc in Document.objects.all():
            self.assertEqual(doc.status, 'processed')
            self.assertEqual(len(doc.pages), 3)
            self.assertGreater(len(doc.extraction['requirements']), 0)
            for req in doc.extraction['requirements']:
                self.assertTrue(evidence_valid(doc.pages, req['page'], req['quote']))

    def test_positive_unknown_and_negative_are_separate(self):
        energy = self.detail('energy-iot')
        self.assertEqual(energy['match']['recommendation'], 'recommended')
        self.assertTrue(all(c['status'] == 'met' for c in energy['match']['conditions']))
        sport = self.detail('sport-portal')
        self.assertEqual(sport['match']['level'], 'high')
        self.assertEqual(sport['match']['recommendation'], 'review')
        self.assertIn('unknown', [c['status'] for c in sport['match']['conditions']])
        self.assertEqual(self.detail('office-licenses')['match']['level'], 'low')

    def test_lot_matching_is_separate(self):
        lots = self.detail('lab-platform')['lots']
        self.assertEqual(lots[0]['match_level'], 'low')
        self.assertEqual(lots[1]['match_level'], 'high')

    def test_profile_update_recalculates_conditions(self):
        profile = get_profile()
        profile['staff_count'] = 1
        response = self.client.put('/api/profile', profile, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'user')
        result = self.detail('energy-iot')
        self.assertEqual(result['match']['recommendation'], 'unsuitable')
        self.assertEqual(next(c for c in result['match']['conditions'] if c['id'] == 'energy-staff')['status'], 'unmet')

    def test_completing_reference_resolves_unknown(self):
        profile = get_profile()
        profile['references'][1].update(value=80000, year=today().year - 1)
        self.client.put('/api/profile', profile, format='json')
        result = self.detail('sport-portal')
        self.assertTrue(all(c['status'] == 'met' for c in result['match']['conditions'] if c['id'] != 'sport-certification'))
        self.assertEqual(result['match']['recommendation'], 'review')
        profile['certifications'] = ['ISO 27001']
        self.client.put('/api/profile', profile, format='json')
        self.assertEqual(self.detail('sport-portal')['match']['recommendation'], 'recommended')

    def test_unknown_not_equal_to_met(self):
        req = {'id': 'test', 'title': 'Staff', 'kind': 'staff', 'minimum': 3}
        self.assertEqual(evaluate_requirement(req, {'staff_count': None})['status'], 'unknown')
        req['minimum'] = None
        self.assertEqual(evaluate_requirement(req, {'staff_count': 6})['status'], 'unknown')

    def test_reference_age_boundary_is_unknown_without_exact_date(self):
        profile = get_profile()
        profile['references'][0]['year'] = today().year - 3
        req = {'id': 'test', 'title': 'Referenca', 'kind': 'reference_count', 'minimum': 1, 'domain': 'energy', 'max_age_years': 3}
        self.assertEqual(evaluate_requirement(req, profile)['status'], 'unknown')

    def test_partial_technology_overlap_does_not_confirm_whole_requirement(self):
        req = {'id': 'tech', 'title': 'React in Django', 'kind': 'technology', 'technologies': ['React', 'Django']}
        self.assertEqual(evaluate_requirement(req, {'technologies': ['React']})['status'], 'unknown')
        self.assertEqual(evaluate_requirement(req, {'technologies': ['React', 'Django']})['status'], 'met')

    def test_finite_numbers_only(self):
        for value in [float('nan'), float('inf'), -1]:
            with self.assertRaises(ValidationError):
                validate_profile({'staff_count': value}, get_profile())

    def test_filters_AND_groups_OR_members(self):
        result = apply_filters(all_tenders(), {'view': 'all', 'q': 'IoT, športnih', 'regions': ['Podravska', 'Osrednjeslovenska'], 'kinds': ['services'], 'statuses': ['open']})
        self.assertEqual({t['id'] for t in result}, {'energy-iot', 'sport-portal'})

    def test_cpv_hierarchy(self):
        result = apply_filters(all_tenders(), {'view': 'all', 'cpv': ['72000000']})
        self.assertIn('energy-iot', {t['id'] for t in result})
        self.assertNotIn('office-licenses', {t['id'] for t in result})

    def test_unknown_value_can_be_included_or_excluded(self):
        yes = apply_filters(all_tenders(), {'view': 'all', 'min_value': 200000, 'include_unknown': True})
        no = apply_filters(all_tenders(), {'view': 'all', 'min_value': 200000, 'include_unknown': False})
        self.assertIn('lab-platform', {t['id'] for t in yes})
        self.assertNotIn('lab-platform', {t['id'] for t in no})

    def test_unknown_date_preserved_and_filterable(self):
        self.assertIsNone(self.detail('ijs-archive')['published_at'])
        yes = apply_filters(all_tenders(), {'view': 'all', 'published_from': '2026-01-01', 'include_unknown': True})
        no = apply_filters(all_tenders(), {'view': 'all', 'published_from': '2026-01-01', 'include_unknown': False})
        self.assertIn('ijs-archive', {t['id'] for t in yes})
        self.assertNotIn('ijs-archive', {t['id'] for t in no})

    def test_correction_idempotent_and_recommendation_changes(self):
        before = self.detail('satellite')
        self.assertEqual(before['match']['recommendation'], 'recommended')
        event = trigger_event('correction')
        after = self.detail('satellite')
        self.assertTrue(event['created'])
        self.assertEqual(after['version'], 2)
        self.assertEqual(after['match']['recommendation'], 'unsuitable')
        self.assertEqual(after['documents'][0]['id'], 'satellite-v2')
        self.assertFalse(trigger_event('correction')['created'])
        self.assertEqual(Notification.objects.filter(type='correction').count(), 1)

    def test_unmet_disappears_from_recommended_but_stays_following(self):
        trigger_event('correction')
        recommended = apply_filters(all_tenders(), {})
        followed = apply_filters(all_tenders(), {'view': 'following'})
        self.assertNotIn('satellite', {t['id'] for t in recommended})
        self.assertIn('satellite', {t['id'] for t in followed})

    def test_closed_cannot_generate_new_opportunity(self):
        record = Tender.objects.get(pk='energy-iot')
        record.data['status'] = 'closed'
        record.save()
        trigger_event('new')
        self.assertFalse(Notification.objects.filter(type='new').exists())

    def test_new_and_deadline_events_once_only(self):
        self.assertTrue(trigger_event('new')['created'])
        self.assertFalse(trigger_event('new')['created'])
        self.assertTrue(trigger_event('deadline')['created'])
        self.assertFalse(trigger_event('deadline')['created'])
        self.assertEqual(Notification.objects.exclude(type='improvement').count(), 2)

    def test_saved_search_persists_and_replays(self):
        filters = {'view': 'all', 'q': 'IoT', 'min_days': 14, 'include_unknown': True}
        created = self.client.post('/api/searches', {'name': 'IoT priložnosti', 'filters': filters}, format='json')
        self.assertEqual(created.status_code, 201)
        loaded = next(s for s in self.client.get('/api/searches').data if s['id'] == created.data['id'])
        self.assertEqual(loaded['filters'], filters)
        self.assertEqual(apply_filters(all_tenders(), filters), apply_filters(all_tenders(), loaded['filters']))

    def test_document_endpoint_is_real_pdf(self):
        response = self.client.get('/api/documents/energy-v1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_bad_quote_rejected_not_converted_to_valid_condition(self):
        doc = Document.objects.get(pk='energy-v1')
        item = deepcopy(doc.extraction['requirements'][0])
        item['quote'] = 'To besedilo ne obstaja v dokumentu.'
        data = validated_extraction({'requirements': [item]}, doc)
        self.assertEqual(data['requirements'], [])
        self.assertEqual(data['rejected_requirements'], 1)

    def test_missing_threshold_rejected(self):
        doc = Document.objects.get(pk='energy-v1')
        item = deepcopy(doc.extraction['requirements'][0])
        item['minimum'] = None
        data = validated_extraction({'requirements': [item]}, doc)
        self.assertEqual(data['rejected_requirements'], 1)

    def test_unprocessed_attachment_prevents_unqualified_recommendation(self):
        file = SimpleUploadedFile('scanned.txt', b'not a pdf', content_type='text/plain')
        response = self.client.post('/api/tenders/energy-iot/documents', {'file': file}, format='multipart')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'unprocessed')
        self.assertEqual(self.detail('energy-iot')['match']['recommendation'], 'review')

    def test_text_only_extraction_without_AI_analysis_remains_review(self):
        Document.objects.create(id='uploaded-only', tender_id='energy-iot', title='Dodatni pogoji', path='unused.pdf',
            status='processed', pages=[{'page': 1, 'text': 'Dokument vsebuje dodatne pogoje, ki še niso analizirani.'}],
            extraction={'mode': 'unprocessed', 'requirements': [], 'criteria': []})
        self.assertEqual(self.detail('energy-iot')['match']['recommendation'], 'review')

    @patch.dict(os.environ, {'OPENAI_API_KEY': '', 'OPENROUTER_API_KEY': ''})
    def test_chat_demo_uses_current_profile_and_has_evidence(self):
        response = self.client.post('/api/chat', {'message': 'Katere reference moramo dopolniti?', 'tender_ids': ['sport-portal']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'demo')
        self.assertIn('Manjka', response.data['answer'])
        self.assertEqual(response.data['citations'][0]['document_id'], 'sport-v1')

    def test_profile_chat_proposal_does_not_mutate_until_apply(self):
        before = get_profile()
        response = self.client.post('/api/chat', {'message': 'Razvijamo tudi rešitve za senzorje. Posodobi profil.'}, format='json')
        self.assertIn('profile_patch', response.data)
        self.assertEqual(before, get_profile())

    def test_named_comparison_resolves_requested_notices(self):
        result = demo_chat('Primerjaj razpisa za IoT in športno platformo.', all_tenders(), get_profile())
        self.assertEqual({c['tender_id'] for c in result['citations']}, {'energy-iot', 'sport-portal'})

    def test_license_question_explains_low_fit_instead_of_unrelated_recommendations(self):
        result = demo_chat('Zakaj ne priporočaš podaljšanja licenc?', all_tenders(), get_profile())
        self.assertEqual(result['citations'][0]['tender_id'], 'office-licenses')
        self.assertIn('slabo ujema', result['answer'])

    def test_prefill_is_explicit_demo_and_does_not_mutate(self):
        before = get_profile()
        result = self.client.post('/api/profile/prefill', {'provider': 'demo', 'query': 'poljubno podjetje'}, format='json')
        self.assertEqual(result.data['source'], 'demo')
        self.assertIn('izmišljeni', result.data['message'])
        self.assertEqual(before, get_profile())

    def test_cross_origin_mutation_is_blocked(self):
        response = self.client.post('/api/demo/reset', {}, format='json', HTTP_ORIGIN='https://attacker.example')
        self.assertEqual(response.status_code, 403)

    def test_reset_restores_demo_and_clears_events(self):
        trigger_event('correction')
        response = self.client.post('/api/demo/reset', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.exclude(type='improvement').count(), 0)
        self.assertEqual(self.detail('satellite')['version'], 1)

    def test_invalid_filter_dates_return_400_not_500(self):
        response = self.client.get('/api/tenders?published_from=nonsense')
        self.assertEqual(response.status_code, 400)
