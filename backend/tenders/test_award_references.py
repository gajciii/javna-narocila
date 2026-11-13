from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from tenders.award_references import company_awards
from tenders.matching import evaluate_requirement
from tenders.models import PastAward

REG = '2372878000'


def award(pk, winners, awarded=True, **data):
    return PastAward.objects.create(id=pk, notice_id=pk.split('-')[1], published_on=date(2026, 3, 12), data={
        'title': 'Servis laboratorijske opreme', 'lot_title': '', 'buyer': 'ZD Maribor', 'description': 'Vzdrževanje opreme.',
        'cpv': ['50410000'], 'currency': 'EUR', 'awarded_value': 131000.0, 'notice_number': 'JN001/2026-ODL/01',
        'awarded': awarded, 'winners': winners, **data})


class AwardReferenceTests(TestCase):
    def setUp(self):
        award('pjn-1-1', [{'name': 'VIPTRONIK d.o.o.', 'registration_number': REG}])
        award('pjn-2-1', [{'name': 'Drugo d.o.o.', 'registration_number': '1' + REG[1:]}])  # different company
        award('pjn-3-1', [{'name': 'VIPTRONIK d.o.o.', 'registration_number': REG}], awarded=False)
        award('pjn-4-7', [{'name': 'VIPTRONIK d.o.o.', 'registration_number': REG}, {'name': 'Partner', 'registration_number': '1234567000'}],
              cpv=['45000000'], lot_title='Sklop 2', currency='USD')

    def test_finds_only_exact_registration_wins(self):
        result = company_awards({'registration_number': '2372878', 'references': []})
        self.assertEqual([i['reference']['id'] for i in result['items']], ['award-pjn-1-1', 'award-pjn-4-7'])
        joint = result['items'][1]
        self.assertTrue(joint['joint'])
        self.assertEqual(joint['reference']['title'], 'Servis laboratorijske opreme – Sklop 2')
        self.assertEqual((joint['reference']['domain'], joint['reference']['value']), ('construction', None))

    def test_reference_counts_for_reference_conditions(self):
        ref = company_awards({'registration_number': REG, 'references': []})['items'][0]['reference']
        self.assertTrue(ref['confirmed'])
        self.assertEqual((ref['year'], ref['value']), (2026, 131000.0))
        self.assertTrue(ref['evidence_url'].startswith('https://www.enarocanje.si/'))
        profile = {'references': [ref]}
        self.assertEqual(evaluate_requirement({'id': 'r', 'title': 'Referenca', 'kind': 'reference_value', 'minimum': 100000}, profile)['status'], 'met')
        self.assertEqual(evaluate_requirement({'id': 'r', 'title': 'Referenca', 'kind': 'reference_count', 'minimum': 1, 'max_age_years': 3}, profile)['status'], 'met')

    def test_marks_already_added_and_requires_registration(self):
        ref = company_awards({'registration_number': REG, 'references': []})['items'][0]['reference']
        result = company_awards({'registration_number': REG, 'references': [{'id': 'x', 'project_identifier': ref['project_identifier']}]})
        self.assertTrue(result['items'][0]['added'])
        self.assertIn('message', company_awards({'registration_number': '', 'references': []}))

    def test_saved_references_pass_profile_validation(self):
        client = APIClient()
        if True:
            profile = client.get('/api/profile').data
            ref = company_awards({'registration_number': REG, 'references': []})['items'][0]['reference']
            saved = client.put('/api/profile', {**profile, 'references': [ref]}, format='json')
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(saved.data['references'][0]['evidence_url'], ref['evidence_url'])
