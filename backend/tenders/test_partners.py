from copy import deepcopy
from datetime import timedelta
from django.test import TestCase
from rest_framework.test import APIClient
from .models import CompanyProfile, Document, Partner, Tender, Notification
from .seed import ensure_seed, get_profile, today
from .improvements import company_key
from .filtering import apply_filters, validate_filters
from .matching import serialize_tender, evaluate_requirement
from .partners import compare_partner, condition_set, partner_recommendations, certification_catalog
from .services import trigger_event
from rest_framework.exceptions import ValidationError


class PartnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def setUp(self):
        self.client = APIClient()

    def profile(self, **patch):
        obj = CompanyProfile.objects.get(pk=1)
        obj.data = {**obj.data, **patch}
        obj.save()
        return get_profile()

    def ref(self, project='PROJECT-B', **patch):
        return {'id': project, 'project_identifier': project, 'title': project, 'description': 'Razvoj',
                'domain': 'sport', 'year': today().year - 1, 'value': 70000, 'confirmed': True,
                'evidence_source': 'Potrdilo naročnika', 'evidence_url': '', **patch}

    def partner(self, source='demo', **patch):
        return Partner.objects.create(company_key=company_key(), source_type=source, data={
            'name': 'Partner', 'registration_number': 'PARTNER', 'description': 'Razvoj spletnih aplikacij',
            'technologies': [], 'certifications': [], 'staff_count': None, 'available_from': today().isoformat(),
            'references': [], 'capability_evidence': {'source': 'Izjava partnerja', 'url': '', 'confirmed': True}, **patch})

    def tender(self, requirements, source='demo', status='open'):
        original = Tender.objects.get(pk='energy-iot')
        tender = Tender.objects.create(id='partner-test', data={**original.data, 'id': 'partner-test', 'source_type': source, 'status': status})
        rows = [{'id': str(i), 'title': 'Pogoj ' + str(i), 'minimum': 1, 'page': 1, 'quote': 'Dokumentiran pogoj', 'document_id': 'partner-test-doc', **r} for i, r in enumerate(requirements)]
        doc = Document.objects.create(id='partner-test-doc', tender=tender, title='Pogoji', path='', status='processed', pages=[{'page': 1, 'text': 'Dokumentiran pogoj'}], extraction={'mode': 'live', 'requirements': rows})
        return tender, doc

    def compare(self, requirements, partner, profile=None):
        tender, doc = self.tender(requirements)
        profile = profile or get_profile()
        return compare_partner(tender, profile, partner, condition_set(tender, profile, [doc]), serialize_tender(tender, profile, [doc]))

    def test_score_boundaries_and_bad_values(self):
        tender = serialize_tender(Tender.objects.get(pk='energy-iot'), get_profile())
        for score in [0, tender['match']['score']]:
            self.assertEqual(len(apply_filters([tender], {'min_score': score})), 1)
        self.assertEqual(apply_filters([tender], {'min_score': 100}), [])
        for bad in [-1, 101, 0.5, True, 'nan', 'inf']:
            with self.assertRaises(ValidationError):
                validate_filters({'min_score': bad})

    def test_partner_toggle_retains_all_other_constraints(self):
        trigger_event('correction')
        tender = serialize_tender(Tender.objects.get(pk='satellite'), get_profile())
        self.assertEqual(tender['match']['recommendation'], 'unsuitable')
        self.assertFalse(apply_filters([tender], {}))
        enabled = {'include_partner_opportunities': True}
        self.assertEqual(len(apply_filters([tender], enabled)), 1)
        self.assertFalse(apply_filters([tender], {**enabled, 'min_score': 100}))
        self.assertFalse(apply_filters([tender], {**enabled, 'q': 'unrelated'}))
        self.assertFalse(apply_filters([tender], {**enabled, 'levels': ['low']}))
        for status in ['closed', 'cancelled', 'unconfirmed']:
            self.assertFalse(apply_filters([{**tender, 'status': status}], enabled))
        self.assertFalse(apply_filters([{**tender, 'match': {**tender['match'], 'level': 'low'}}], enabled))

    def test_saved_filters_roundtrip_and_legacy_levels(self):
        filters = {'min_score': 71, 'include_partner_opportunities': True, 'levels': ['high']}
        response = self.client.post('/api/searches', {'name': 'Partnerji', 'filters': filters}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['filters'], filters)
        self.assertIn(response.data, self.client.get('/api/searches').data)
        self.assertEqual(self.client.get('/api/tenders', {'min_score': -1}).status_code, 400)

    def test_reference_support_and_remaining_certificate(self):
        partner = self.partner(references=[self.ref()])
        result = self.compare([{'kind': 'reference_value', 'domain': 'sport', 'minimum': 60000}, {'kind': 'certification', 'certification': 'ISO 27001'}], partner)
        self.assertEqual(result['supported_conditions'], 1)
        self.assertEqual(result['remaining_conditions'], 1)
        self.assertEqual(result['conditions'][0]['state'], 'potential')
        self.assertEqual(result['conditions'][0]['condition']['status'], 'unknown')
        self.assertEqual(result['conditions'][0]['evidence'][0]['source'], 'Potrdilo naročnika')

    def test_unconfirmed_missing_evidence_old_or_unknown_reference(self):
        req = [{'kind': 'reference_value', 'domain': 'sport', 'minimum': 60000, 'max_age_years': 3}]
        tender, doc = self.tender(req)
        profile = get_profile()
        for patch in [{'confirmed': False}, {'evidence_source': ''}, {'year': today().year - 5}, {'year': None}, {'value': None}, {'year': today().year + 1}]:
            partner = self.partner(references=[self.ref(**patch)])
            result = compare_partner(tender, profile, partner, condition_set(tender, profile, [doc]), serialize_tender(tender, profile, [doc]))
            self.assertEqual(result['supported_conditions'], 0, patch)

    def test_reference_values_are_never_added(self):
        profile = self.profile(references=[self.ref('PROJECT-A', value=40000)])
        result = self.compare([{'kind': 'reference_value', 'domain': 'sport', 'minimum': 60000}], self.partner(references=[self.ref(value=40000)]), profile)
        self.assertEqual(result['supported_conditions'], 0)

    def test_distinct_identified_projects_can_cover_count(self):
        profile = self.profile(references=[self.ref('PROJECT-A')])
        result = self.compare([{'kind': 'reference_count', 'domain': 'sport', 'minimum': 2}], self.partner(references=[self.ref()]), profile)
        self.assertEqual(result['supported_conditions'], 1)
        self.assertEqual(result['conditions'][0]['partner_condition']['status'], 'unmet')

    def test_repeated_project_never_counts_twice(self):
        profile = self.profile(references=[self.ref('SAME')])
        result = self.compare([{'kind': 'reference_count', 'domain': 'sport', 'minimum': 2}], self.partner(references=[self.ref('SAME')]), profile)
        self.assertEqual(result['supported_conditions'], 0)
        req = {'id': 'count', 'title': 'Dve referenci', 'kind': 'reference_count', 'domain': 'sport', 'minimum': 2}
        self.assertNotEqual(evaluate_requirement(req, {'references': [self.ref('SAME'), self.ref('SAME', id='different-row') ]})['status'], 'met')

    def test_missing_project_identifier_cannot_be_pooled(self):
        profile = self.profile(references=[self.ref('PROJECT-A', project_identifier='')])
        result = self.compare([{'kind': 'reference_count', 'domain': 'sport', 'minimum': 2}], self.partner(references=[self.ref()]), profile)
        self.assertEqual(result['supported_conditions'], 0)

    def test_conflicting_project_evidence_stays_unconfirmed(self):
        profile = self.profile(references=[self.ref('SAME')])
        result = self.compare([{'kind': 'reference_count', 'domain': 'sport', 'minimum': 2}], self.partner(references=[self.ref('SAME', value=60000)]), profile)
        self.assertEqual(result['supported_conditions'], 0)

    def test_staff_and_technologies_can_be_complementary(self):
        profile = self.profile(staff_count=2, technologies=['React'])
        partner = self.partner(staff_count=2, technologies=['Rust'])
        result = self.compare([{'kind': 'staff', 'minimum': 4}, {'kind': 'technology', 'technologies': ['React', 'Rust']}], partner, profile)
        self.assertEqual(result['supported_conditions'], 2)

    def test_staff_needs_evidence_and_availability(self):
        tender, doc = self.tender([{'kind': 'staff', 'minimum': 8}])
        for patch in [{'available_from': ''}, {'available_from': (today() + timedelta(days=100)).isoformat()}, {'capability_evidence': {'confirmed': False, 'source': 'Izjava'}}]:
            partner = self.partner(staff_count=8, **patch)
            profile = get_profile()
            self.assertEqual(compare_partner(tender, profile, partner, condition_set(tender, profile, [doc]), serialize_tender(tender, profile, [doc]))['supported_conditions'], 0)

    def test_certificates_stay_partner_facts_and_keep_manual_review(self):
        result = self.compare([{'kind': 'certification', 'certification': 'ISO 27001'}, {'kind': 'certification', 'certification': 'ISO 27001:2022', 'requires_manual_review': True}], self.partner(certifications=['ISO/IEC 27001', 'ISO 27001:2022']))
        self.assertEqual(result['supported_conditions'], 1)
        self.assertEqual(result['conditions'][0]['partner_condition']['status'], 'met')
        self.assertIn('ne postane certifikat vašega podjetja', result['conditions'][0]['explanation'])
        self.assertEqual(get_profile()['certifications'], [])

    def test_api_seeds_four_once_and_deletion_survives_refresh(self):
        first = self.client.get('/api/partners')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.data), 4)
        self.assertEqual(len(self.client.get('/api/partners').data), 4)
        id = first.data[0]['id']
        self.assertEqual(self.client.delete(f'/api/partners/{id}').status_code, 204)
        self.assertEqual(len(self.client.get('/api/partners').data), 3)

    def test_partner_crud_and_company_isolation(self):
        payload = {'source_type': 'real', 'profile': {'name': 'Pravi partner', 'registration_number': '1234567', 'references': [self.ref()]}, 'capability_evidence': {'source': 'Izjava', 'url': 'https://example.com/proof', 'confirmed': True}}
        response = self.client.post('/api/partners', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        id = response.data['id']
        payload['profile']['name'] = 'Popravljen partner'
        self.assertEqual(self.client.put(f'/api/partners/{id}', payload, format='json').data['profile']['name'], 'Popravljen partner')
        self.profile(registration_number='OTHER')
        self.assertNotIn(id, [p['id'] for p in self.client.get('/api/partners').data])
        for method in ['get', 'put', 'delete']:
            self.assertEqual(getattr(self.client, method)(f'/api/partners/{id}', {}, format='json').status_code, 404)
        self.profile(registration_number='DEMO-001')
        self.assertEqual(self.client.get(f'/api/partners/{id}').status_code, 200)

    def test_validation_own_company_urls_and_evidence(self):
        for profile in [{'name': 'Own', 'registration_number': 'DEMO-001'}, {'name': 'Bad', 'website': 'javascript:alert(1)'}, {'name': 'Bad', 'references': [self.ref(evidence_source='')]}, {'name': 'Bad', 'references': [self.ref(evidence_source='   ')]}, {'name': 'Bad', 'references': [self.ref(evidence_url='javascript:alert(1)')]}]:
            self.assertEqual(self.client.post('/api/partners', {'profile': profile}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/partners', {'profile': {'name': 'Bad'}, 'capability_evidence': {'confirmed': True}}, format='json').status_code, 400)

    def test_sources_are_separate_and_explicit_comparison_is_scoped(self):
        tender, _ = self.tender([{'kind': 'certification', 'certification': 'ISO 27001'}], source='real')
        wrong = self.partner(certifications=['ISO 27001'])
        real = self.partner(source='real', certifications=['ISO 27001'])
        foreign = self.partner(source='real', certifications=['ISO 27001'])
        foreign.company_key = 'someone-else'; foreign.save()
        result = self.client.get(f'/api/tenders/{tender.pk}/partners')
        self.assertEqual([x['partner']['id'] for x in result.data['candidates']], [real.id])
        for id in [wrong.id, foreign.id]:
            self.assertEqual(self.client.get(f'/api/tenders/{tender.pk}/partners?partner_id={id}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/tenders/{tender.pk}/partners?partner_id={real.id}').data['comparison']['partner']['id'], real.id)

    def test_ranking_top_three_and_no_profile_or_tender_mutation(self):
        tender, _ = self.tender([{'kind': 'certification', 'certification': 'ISO 27001'}, {'kind': 'staff', 'minimum': 8}], source='real')
        for i in range(4):
            self.partner(source='real', name=f'Partner {i}', certifications=['ISO 27001'])
        best = self.partner(source='real', certifications=['ISO 27001'], staff_count=8)
        before = deepcopy(get_profile())
        records = list(Tender.objects.values('data', 'following'))
        result = partner_recommendations(tender)
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual(result['candidates'][0]['partner']['id'], best.pk)
        self.assertEqual(get_profile(), before)
        self.assertEqual(list(Tender.objects.values('data', 'following')), records)
        self.assertFalse(Notification.objects.exists())

    def test_unprocessed_and_inactive_empty_states(self):
        tender, doc = self.tender([{'kind': 'certification', 'certification': 'ISO 27001'}])
        self.partner(certifications=['ISO 27001'])
        for status in ['closed', 'cancelled', 'unconfirmed']:
            tender.data['status'] = status; tender.save()
            self.assertEqual(partner_recommendations(tender)['candidates'], [])
        tender.data['status'] = 'open'; tender.save()
        doc.status = 'unprocessed'; doc.save()
        self.assertEqual(partner_recommendations(tender)['candidates'], [])
        self.assertIn('analizirani', partner_recommendations(tender)['message'])

    def test_catalog_and_profile_certificate_compatibility(self):
        self.profile(certifications=['ISO 27001', 'iso-27001', 'ISO/IEC 27001:2022', 'Lastni certifikat'])
        values = certification_catalog()
        iso = [x for x in values if x['key'] == 'iso27001']
        self.assertEqual(len(iso), 1)
        self.assertTrue(iso[0]['required'])
        self.assertTrue(any(x['key'] == 'iso27001:2022' for x in values))
        self.assertEqual(self.client.get('/api/certifications').status_code, 200)
        result = self.client.put('/api/profile', {'certifications': ['ISO 27001', 'ISO/IEC 27001', 'ISO 27001:2022']}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['certifications'], ['ISO 27001', 'ISO 27001:2022'])

    def test_profile_reference_evidence_persists(self):
        refs = [self.ref()]
        response = self.client.put('/api/profile', {'references': refs}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['references'], refs)

    def test_duplicate_company_registration_is_normalized(self):
        payload = {'profile': {'name': 'Partner', 'registration_number': '1234567'}}
        self.assertEqual(self.client.post('/api/partners', payload, format='json').status_code, 201)
        payload['profile']['registration_number'] = '1234567000'
        self.assertEqual(self.client.post('/api/partners', payload, format='json').status_code, 400)

    def test_future_project_is_not_completed_even_without_age_limit(self):
        result = self.compare([{'kind': 'reference_value', 'domain': 'sport', 'minimum': 60000}], self.partner(references=[self.ref(year=today().year + 1)]))
        self.assertEqual(result['supported_conditions'], 0)

    def test_unrelated_capability_proof_is_not_presented_as_certificate_evidence(self):
        result = self.compare([{'kind': 'certification', 'certification': 'ISO 27001'}], self.partner(certifications=['ISO 9001']))
        self.assertEqual(result['conditions'][0]['evidence'], [])

    def extracted(self, tender, conditions):
        from .models import TenderConditions
        rows = [{'id': f'c{i}', 'category': 'technical', 'title': f'Pogoj {i}', 'requirement': f'Zahteva {i}',
                 'quote': 'Dokumentiran pogoj', 'document_id': 'partner-test-doc', 'document_title': 'Pogoji',
                 'page': 1, 'locator': 'stran 1', 'check': {'kind': 'none'}, **c} for i, c in enumerate(conditions, 1)]
        return TenderConditions.objects.create(tender=tender, fingerprint='x', mode='live', conditions=rows,
                                               extracted_at='2026-11-12T00:00Z')

    def test_extracted_conditions_and_partner_answers(self):
        tender, _ = self.tender([], source='real')
        self.extracted(tender, [
            {'category': 'economic', 'title': 'Povprečni letni promet', 'requirement': 'Promet najmanj 2.000.000 EUR.'},
            {'category': 'exclusion', 'title': 'Ni blokiranega računa', 'requirement': 'Ponudnik nima blokiranega računa.'},
            {'category': 'technical', 'title': 'Certifikat ISO 27001', 'quote': 'Certifikat ISO 27001',
             'check': {'kind': 'certification', 'certification': 'ISO 27001'}}])
        partner = self.partner(source='real', certifications=['ISO 27001'])
        url = f'/api/tenders/{tender.pk}/partners'
        result = self.client.get(url).data
        self.assertEqual(len(result['missing_conditions']), 3)
        self.assertEqual([c['partner']['id'] for c in result['candidates']], [partner.pk])
        self.assertEqual(result['candidates'][0]['supported_conditions'], 1)
        self.assertEqual(result['partners'][0]['id'], partner.pk)

        response = self.client.post(f'{url}/{partner.pk}/conditions/c1/answer', {'answer': 'met'}, format='json')
        self.assertEqual(response.status_code, 200)
        rows = {r['condition']['id']: r for r in response.data['comparison']['conditions']}
        self.assertEqual(rows['c1']['state'], 'potential')
        self.assertEqual(rows['c1']['partner_condition']['answer']['answer'], 'met')
        self.assertFalse(rows['c1']['partner_condition']['answer']['inherited'])
        self.assertNotIn('condition_answers', response.data['comparison']['partner']['profile'])

        # A partner can never cover exclusion grounds, and an unmet one blocks the partner.
        response = self.client.post(f'{url}/{partner.pk}/conditions/c2/answer', {'answer': 'met'}, format='json')
        self.assertEqual({r['condition']['id']: r['state'] for r in response.data['comparison']['conditions']}['c2'], 'unresolved')
        response = self.client.post(f'{url}/{partner.pk}/conditions/c2/answer', {'answer': 'unmet'}, format='json')
        self.assertEqual(response.data['comparison']['blocked_by'], ['Ni blokiranega računa'])
        self.assertEqual(response.data['candidates'], [])

        response = self.client.post(f'{url}/{partner.pk}/conditions/c2/answer', {'answer': None}, format='json')
        self.assertEqual(response.data['comparison']['blocked_by'], [])
        self.assertEqual(self.client.post(f'{url}/{partner.pk}/conditions/c9/answer', {'answer': 'met'}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f'{url}/{partner.pk}/conditions/c1/answer', {'answer': 'maybe'}, format='json').status_code, 400)
        # Editing the partner keeps its condition marks.
        self.client.put(f'/api/partners/{partner.pk}', {'profile': {'name': 'Preimenovan'}}, format='json')
        partner.refresh_from_db()
        self.assertEqual(len(partner.data['condition_answers']), 1)

    def test_partner_answers_apply_to_foreign_partner_only_in_scope(self):
        tender, _ = self.tender([], source='real')
        self.extracted(tender, [{'category': 'economic', 'title': 'Povprečni letni promet'}])
        foreign = self.partner(source='real')
        foreign.company_key = 'someone-else'; foreign.save()
        url = f'/api/tenders/{tender.pk}/partners/{foreign.pk}/conditions/c1/answer'
        self.assertEqual(self.client.post(url, {'answer': 'met'}, format='json').status_code, 404)

    def test_no_partners_message(self):
        tender, _ = self.tender([], source='real')
        self.extracted(tender, [{'category': 'economic', 'title': 'Povprečni letni promet'}])
        result = partner_recommendations(tender)
        self.assertEqual(result['partners'], [])
        self.assertIn('nimate vnesenih partnerjev', result['message'])
