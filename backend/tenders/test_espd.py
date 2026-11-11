"""ESPD drafts: verified prefill, no automatic sworn declarations, per-company isolation."""
from django.test import TestCase
from rest_framework.test import APIClient

from .models import CompanyProfile, EspdDraft
from .seed import demo_profile, ensure_seed


class EspdTests(TestCase):
    def setUp(self):
        ensure_seed(reset=True)
        self.client = APIClient()
        profile = CompanyProfile.objects.get(pk=1)
        profile.data = {**demo_profile(), 'certifications': ['ISO 27001']}
        profile.save()

    def get(self, tender='sport-portal'):
        response = self.client.get(f'/api/tenders/{tender}/espd')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def answers(self, **overrides):
        body = {'operator': {'vat_id': 'SI 12345678', 'contact_name': 'Ana Novak', 'email': 'ana@example.com', 'phone': '', 'size': 'small',
                             'representatives': [{'name': 'Ana Novak', 'role': 'direktorica'}]},
                'participation': {'lots': [], 'joint_bid': False, 'relies_on_others': False, 'subcontracting': False},
                'exclusion': {}, 'selection': {'responses': {}}, 'final': {'place': 'Maribor', 'date': '2026-11-11', 'signatory': 'Ana Novak'}}
        body.update(overrides)
        return body

    def test_get_prefills_sources_and_never_answers_exclusion_grounds(self):
        espd = self.get()
        self.assertEqual(espd['part1']['buyer'], 'Javni zavod Športni center Primer')
        self.assertEqual(espd['part2'][0]['value'], 'Lumina digital d.o.o.')
        self.assertEqual(espd['answers']['exclusion'], {})
        self.assertTrue(espd['part3'][0]['items'])
        self.assertIn('Demo razpis', ' '.join(espd['warnings']))
        self.assertFalse(EspdDraft.objects.exists(), 'GET must not create a draft')

    def test_part4_rows_cite_document_and_suggest_profile_evidence(self):
        rows = self.get()['part4']
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row['document_id'] and row['page'] and row['quote'])
        cert = next(r for r in rows if r['kind'] == 'certification')
        self.assertEqual(cert['section'], 'D')
        self.assertIn('ISO 27001', cert['response'])
        reference = next(r for r in rows if r['kind'] == 'reference_count')
        self.assertIn('Platforma za športna tekmovanja', reference['response'])

    def test_put_validates_saves_and_overrides_suggestion(self):
        row = self.get()['part4'][0]
        body = self.answers(selection={'responses': {row['id']: 'Lastni opis.'}}, exclusion={'taxes': {'answer': 'no'}})
        espd = self.client.put('/api/tenders/sport-portal/espd', body, format='json').json()
        self.assertEqual(espd['answers']['operator']['vat_id'], 'SI12345678')
        edited = next(r for r in espd['part4'] if r['id'] == row['id'])
        self.assertEqual((edited['response'], edited['edited']), ('Lastni opis.', True))
        self.assertEqual(espd['answers']['exclusion']['taxes']['answer'], 'no')
        self.assertEqual(self.get()['answers']['operator']['contact_name'], 'Ana Novak')

    def test_invalid_values_are_rejected(self):
        for bad in [self.answers(operator={'email': 'ni-mail'}), self.answers(operator={'vat_id': '12'}),
                    self.answers(exclusion={'taxes': {'answer': 'maybe'}}), self.answers(participation={'lots': ['missing']}),
                    self.answers(final={'date': '11. 11.'})]:
            self.assertEqual(self.client.put('/api/tenders/sport-portal/espd', bad, format='json').status_code, 400)

    def test_company_details_carry_over_but_declarations_do_not(self):
        self.client.put('/api/tenders/sport-portal/espd', self.answers(exclusion={'taxes': {'answer': 'no'}}), format='json')
        other = self.get('energy-iot')
        self.assertEqual(other['answers']['operator']['vat_id'], 'SI12345678')
        self.assertEqual(other['answers']['final']['signatory'], 'Ana Novak')
        self.assertEqual(other['answers']['final']['date'], '')
        self.assertEqual(other['answers']['exclusion'], {})

    def test_drafts_are_isolated_per_company_and_resettable(self):
        self.client.put('/api/tenders/sport-portal/espd', self.answers(), format='json')
        profile = CompanyProfile.objects.get(pk=1)
        profile.data = {**profile.data, 'registration_number': '1234567000', 'name': 'Drugo podjetje d.o.o.'}
        profile.save()
        self.assertEqual(self.get()['answers']['operator']['vat_id'], '')
        self.assertEqual(self.client.delete('/api/tenders/sport-portal/espd').status_code, 204)
        self.assertEqual(EspdDraft.objects.count(), 1)

    def test_lots_must_exist_and_are_required_for_progress(self):
        espd = self.get('lab-platform')
        self.assertIn('Izbrani sklopi', espd['progress']['missing'])
        saved = self.client.put('/api/tenders/lab-platform/espd', self.answers(participation={'lots': ['lab-software']}), format='json').json()
        self.assertNotIn('Izbrani sklopi', saved['progress']['missing'])
