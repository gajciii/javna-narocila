from copy import deepcopy
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from .models import CompanyProfile, Document, Notification, Tender, ImprovementPlan
from .seed import ensure_seed, get_profile, today
from .matching import evaluate_requirement, serialize_tender
from .documents import validated_extraction
from .improvements import evaluate, refresh_suggestions, visible_notifications, clean_actions, company_key
from .services import trigger_event

ISO = {'kind': 'certification', 'certification': 'ISO 27001'}


class ImprovementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def setUp(self):
        self.client = APIClient()

    def profile(self, **changes):
        record = CompanyProfile.objects.get(pk=1)
        record.data = {**record.data, **changes}
        record.save()
        return record.data

    def suggestion(self, kind='certification', source='demo'):
        refresh_suggestions()
        return next(n for n in visible_notifications() if n.type == 'improvement' and n.payload['source_type'] == source and n.payload['actions'][0]['kind'] == kind)

    def cert_document(self, tender, id, *, second=False):
        quote = 'Ponudnik mora imeti certifikat ISO 27001.'
        req = {'id': id, 'kind': 'certification', 'certification': 'ISO 27001', 'title': 'ISO 27001', 'page': 1, 'quote': quote, 'document_id': id}
        return Document.objects.create(id=id, tender=tender, title='Dokaz', path='', status='processed', pages=[{'page': 1, 'text': quote}],
            extraction={'mode': 'live', 'requirements': [req, {**req, 'id': id + '-2'}] if second else [req]})

    def extra_tender(self, id, source='demo', status='open'):
        original = Tender.objects.get(pk='energy-iot')
        tender = Tender.objects.create(id=id, data={**original.data, 'id': id, 'source_type': source, 'status': status})
        self.cert_document(tender, id + '-doc')
        return tender

    def test_certification_variants_and_manual_review(self):
        req = {'id': 'cert', 'title': 'ISO', 'kind': 'certification', 'certification': 'ISO 27001', 'quote': 'Ponudnik mora imeti certifikat ISO 27001.'}
        for name in ['ISO 27001', 'iso-27001', 'ISO/IEC 27001', 'ISO IEC 27001']:
            self.assertEqual(evaluate_requirement(req, {'certifications': [name]})['status'], 'met')
        for altered in [{**req, 'certification': 'ISO 27001:2022'}, {**req, 'quote': 'Zahtevan je veljaven ISO 27001.'}, {**req, 'requires_manual_review': True}]:
            self.assertEqual(evaluate_requirement(altered, {'certifications': ['ISO 27001', 'ISO 27001:2022']})['status'], 'unknown')
        self.assertEqual(evaluate_requirement(req, {'certifications': []})['status'], 'unknown')
        self.assertEqual(evaluate_requirement(req, {'certifications': ['ISO 9001']})['status'], 'unknown')

    def test_certification_extraction_requires_evidence_and_name(self):
        doc = Document.objects.get(pk='sport-v1')
        req = next(r for r in doc.extraction['requirements'] if r['kind'] == 'certification')
        self.assertEqual(len(validated_extraction({'requirements': [req]}, doc)['requirements']), 1)
        for bad in [{**req, 'quote': 'Ponudnik samodejno izpolnjuje vse pogoje.'}, {**req, 'certification': 'ISO 9001'}, {**req, 'certification': None}, {**req, 'requires_manual_review': 'false'}]:
            self.assertEqual(validated_extraction({'requirements': [bad]}, doc)['requirements'], [])

    def test_iso_effect_open_and_history_separate_without_writes(self):
        original = deepcopy(get_profile())
        tenders = list(Tender.objects.values('id', 'data', 'following'))
        result = self.client.post('/api/improvements/evaluate', {'actions': [ISO], 'source_type': 'demo'}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['summary']['open']['affected_tenders'], 1)
        self.assertEqual(result.data['summary']['open']['newly_recommended'], 0)
        self.assertEqual(result.data['summary']['open']['needs_data'], 1)
        self.assertEqual(result.data['summary']['historical']['affected_tenders'], 1)
        self.assertEqual(result.data['historical'][0]['after_recommendation'], 'closed')
        self.assertTrue(result.data['open'][0]['remaining_conditions'])
        self.assertEqual(get_profile(), original)
        self.assertEqual(list(Tender.objects.values('id', 'data', 'following')), tenders)
        self.assertFalse(Notification.objects.exists())

    def test_combined_reference_and_certificate_and_no_double_count(self):
        action = {'kind': 'reference', 'domain': 'sport', 'minimum_count': 1, 'minimum_value': 80000, 'max_age_years': 3}
        result = evaluate([ISO, action], 'demo')
        self.assertEqual(result['summary']['open']['affected_tenders'], 1)
        self.assertEqual(result['summary']['open']['improved_conditions'], 3)
        self.assertEqual(result['summary']['open']['newly_recommended'], 1)
        self.profile(certifications=['ISO/IEC 27001'], references=[*get_profile()['references'], {'id': 'actual', 'domain': 'sport', 'year': today().year, 'value': 80000, 'confirmed': True}])
        self.assertEqual(evaluate([ISO, action], 'demo')['summary']['open']['affected_tenders'], 0)

    def test_staff_and_technology_changes_keep_unrelated_unknowns(self):
        self.profile(staff_count=1)
        self.assertEqual(evaluate([{'kind': 'staff', 'minimum': 3}], 'demo')['summary']['open']['newly_recommended'], 1)
        doc = Document.objects.get(pk='energy-v1')
        req = {'id': 'tech', 'title': 'React in Rust', 'kind': 'technology', 'technologies': ['React', 'Rust'], 'document_id': doc.id, 'page': 2, 'quote': 'Test requirement'}
        doc.extraction['requirements'].append(req)
        doc.save()
        result = evaluate([{'kind': 'technology', 'technologies': ['Rust']}], 'demo')
        self.assertEqual(result['summary']['open']['affected_tenders'], 1)
        self.assertEqual(result['summary']['open']['newly_recommended'], 0)
        self.assertIn('unmet', [c['status'] for c in result['open'][0]['remaining_conditions']])

    def test_missing_reference_and_staff_create_completion_not_acquisition(self):
        self.profile(staff_count=None)
        refresh_suggestions()
        actions = [n.payload['actions'][0] for n in visible_notifications() if n.type == 'improvement']
        self.assertIn({'kind': 'complete_profile', 'field': 'staff_count', 'domain': ''}, actions)
        self.assertIn({'kind': 'complete_profile', 'field': 'references', 'domain': 'sport'}, actions)
        self.assertFalse(any(a['kind'] in ('reference', 'staff') for a in actions))
        result = evaluate([{'kind': 'complete_profile', 'field': 'references', 'domain': 'sport'}], 'demo')
        self.assertEqual(result['summary']['open']['affected_tenders'], 0)
        self.assertEqual(result['summary']['open']['needs_data'], 1)

    def test_known_reference_shortage_suggests_target_and_combines_idempotently(self):
        trigger_event('correction')
        item = self.suggestion('reference')
        result = evaluate(item.payload['actions'] * 2, 'demo')
        self.assertEqual(result['summary']['open']['newly_recommended'], 1)
        self.assertEqual(len(result['actions']), 1)

    def test_repeat_poll_preserves_read_and_new_tender_reopens_same_notification(self):
        item = self.suggestion()
        item.read = True
        item.save()
        count = Notification.objects.count()
        refresh_suggestions()
        item.refresh_from_db()
        self.assertTrue(item.read)
        self.assertEqual(Notification.objects.count(), count)
        self.extra_tender('extra')
        refresh_suggestions()
        item.refresh_from_db()
        self.assertFalse(item.read)
        self.assertEqual(item.payload['summary']['open']['affected_tenders'], 2)
        self.assertEqual(Notification.objects.filter(event_key=item.event_key).count(), 1)

    def test_equivalent_certificate_spellings_share_one_suggestion(self):
        tender = self.extra_tender('variant')
        doc = tender.document_records.first()
        doc.extraction['requirements'][0]['certification'] = 'ISO/IEC 27001'
        doc.save()
        refresh_suggestions()
        items = [n for n in visible_notifications() if n.type == 'improvement' and n.payload['actions'][0]['kind'] == 'certification']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].payload['summary']['open']['affected_tenders'], 2)

    def test_remaining_condition_resolved_reopens_notification(self):
        item = self.suggestion()
        item.read = True
        item.save()
        refs = get_profile()['references']
        refs[1].update(value=80000, year=today().year - 1)
        self.profile(references=refs)
        refresh_suggestions()
        item.refresh_from_db()
        self.assertFalse(item.read)
        self.assertEqual(item.payload['summary']['open']['newly_recommended'], 1)

    def test_expiry_moves_effect_to_history_without_new_opportunity(self):
        item = self.suggestion()
        item.read = True
        item.save()
        tender = Tender.objects.get(pk='sport-portal')
        tender.data['deadline'] = '2000-01-01T12:00:00+01:00'
        tender.save()
        refresh_suggestions()
        item.refresh_from_db()
        self.assertTrue(item.read)
        self.assertEqual(item.payload['summary']['open']['affected_tenders'], 0)
        self.assertEqual(item.payload['summary']['historical']['affected_tenders'], 2)

    def test_achieved_or_removed_requirement_hides_notification_preserves_plan(self):
        item = self.suggestion()
        plan = ImprovementPlan.objects.create(company_key=company_key(), name='ISO', actions=[ISO], source_type='demo')
        self.profile(certifications=['ISO 27001'])
        refresh_suggestions()
        item.refresh_from_db()
        self.assertFalse(item.active)
        self.assertNotIn(item, visible_notifications())
        self.assertTrue(ImprovementPlan.objects.filter(pk=plan.pk).exists())
        response = self.client.get(f'/api/improvement-plans/{plan.pk}')
        self.assertEqual(response.data['evaluation']['summary']['open']['affected_tenders'], 0)

    def test_demo_real_counts_separate_and_cancelled_unconfirmed_low_excluded(self):
        self.extra_tender('real', 'real')
        self.extra_tender('cancel', status='cancelled')
        self.extra_tender('unknown', status='unconfirmed')
        low = self.extra_tender('low')
        low.data.update(kind='goods', topics=['dobava licenc'], technologies=[])
        low.save()
        self.assertEqual(evaluate([ISO], 'real')['summary']['open']['affected_tenders'], 1)
        self.assertEqual(evaluate([ISO], 'demo')['summary']['open']['affected_tenders'], 1)
        self.assertNotEqual(self.suggestion(source='demo').pk, self.suggestion(source='real').pk)

    def test_multiple_conditions_count_one_tender_and_incomplete_docs_block_recommendation(self):
        tender = self.extra_tender('duplicate')
        self.cert_document(tender, 'duplicate-extra', second=True)
        Document.objects.create(id='unread', tender=tender, title='Sken', path='', status='unprocessed', extraction={'mode': 'unprocessed'})
        result = evaluate([ISO], 'demo')
        row = next(r for r in result['open'] if r['id'] == 'duplicate')
        self.assertEqual(len(row['changes']), 3)
        self.assertTrue(row['documentation_incomplete'])
        self.assertFalse(row['newly_recommended'])
        self.assertEqual(result['summary']['open']['affected_tenders'], 2)

    def test_at_most_five_unsaved_and_real_first(self):
        for index in range(8):
            tender = self.extra_tender(f'extra-{index}', 'real' if index == 7 else 'demo')
            doc = tender.document_records.first()
            doc.extraction['requirements'][0]['certification'] = f'STANDARD {index}'
            doc.save()
        refresh_suggestions()
        items = list(visible_notifications().filter(type='improvement'))
        self.assertEqual(len(items), 5)
        self.assertTrue(any(n.payload['source_type'] == 'real' for n in items))

    def test_plan_crud_company_isolation_and_canonical_registration(self):
        original = get_profile()
        self.profile(registration_number='1234567')
        response = self.client.post('/api/improvement-plans', {'name': 'Načrt ISO', 'actions': [ISO], 'source_type': 'demo'}, format='json')
        self.assertEqual(response.status_code, 201)
        id = response.data['id']
        self.profile(registration_number='1234567000')
        self.assertEqual(self.client.get(f'/api/improvement-plans/{id}').status_code, 200)
        response = self.client.put(f'/api/improvement-plans/{id}', {'name': 'Preimenovan', 'actions': [ISO, {'kind': 'staff', 'minimum': 8}]}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['actions']), 2)
        self.profile(registration_number='7654321000')
        self.assertEqual(self.client.get('/api/improvement-plans').data, [])
        for method in ['get', 'put', 'delete']:
            self.assertEqual(getattr(self.client, method)(f'/api/improvement-plans/{id}').status_code, 404)
        self.profile(registration_number='1234567')
        self.assertEqual(self.client.delete(f'/api/improvement-plans/{id}').status_code, 204)
        self.assertEqual(get_profile()['references'], original['references'])

    def test_notification_identity_and_read_api(self):
        item = self.suggestion()
        response = self.client.post('/api/notifications/read', {'id': item.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(next(n for n in response.data if n['id'] == item.pk)['read'])
        self.profile(registration_number='different-company')
        self.assertNotIn(item, visible_notifications())
        self.assertEqual(self.client.post('/api/notifications/read', {'id': item.pk}, format='json').status_code, 404)

    def test_invalid_payloads_fail_without_profile_mutation(self):
        original = get_profile()
        for actions in [[], [ISO] * 21, [{'kind': 'staff', 'minimum': -1}], [{'kind': 'staff', 'minimum': True}], [{'kind': 'reference', 'domain': ''}], [{'kind': 'anything'}], [{'kind': 'technology', 'technologies': ['']}]]:
            self.assertEqual(self.client.post('/api/improvements/evaluate', {'actions': actions, 'source_type': 'demo'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/improvements/evaluate', {'actions': [ISO], 'source_type': 'all'}, format='json').status_code, 400)
        self.assertEqual(get_profile(), original)

    def test_simulation_never_calls_external_services(self):
        with patch('requests.get', side_effect=AssertionError('No network')), patch('tenders.ai.structured_call', side_effect=AssertionError('No AI')):
            self.assertEqual(evaluate([ISO], 'demo')['summary']['open']['affected_tenders'], 1)
            refresh_suggestions()

    def test_unprocessed_document_cannot_supply_confirmed_improvement(self):
        doc = Document.objects.get(pk='sport-v1')
        doc.status = 'unprocessed'
        doc.save()
        self.assertEqual(evaluate([ISO], 'demo')['summary']['open']['affected_tenders'], 0)

    def test_document_correction_updates_effect_using_current_version_only(self):
        tender = Tender.objects.get(pk='sport-portal')
        item = self.suggestion()
        doc = Document.objects.get(pk='sport-v1')
        Document.objects.create(id='sport-v2', tender=tender, title=doc.title, path='', version=2, status='processed', pages=doc.pages,
                                extraction={'mode': 'demo', 'requirements': [r for r in doc.extraction['requirements'] if r['kind'] != 'certification']})
        tender.data['version'] = 2
        tender.save()
        refresh_suggestions()
        item.refresh_from_db()
        self.assertEqual(item.payload['summary']['open']['affected_tenders'], 0)
        self.assertEqual(item.payload['summary']['historical']['affected_tenders'], 1)
