from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from tenders.models import CompanyProfile, PastAward, Partner, Tender, TenderConditions
from tenders.partner_suggestions import suggestions
from tenders.seed import ensure_seed

A, B, OWN = '1111111000', '2222222000', '3333333000'


def award(pk, winners, title='Vzdrževanje informacijskega sistema za evidenco pacientov', **data):
    return PastAward.objects.create(id=pk, notice_id=pk.split('-')[1], published_on=date(2026, 3, 12), data={
        'title': title, 'lot_title': '', 'buyer': 'UKC Ljubljana', 'description': 'Vzdrževanje in razvoj informacijskega sistema.',
        'cpv': ['72267000'], 'currency': 'EUR', 'awarded_value': 100000.0, 'notice_number': f'JN{pk}/2026', 'awarded': True,
        'winners': [{'name': name, 'registration_number': number} for name, number in winners], **data})


class PartnerSuggestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed()

    def setUp(self):
        self.client = APIClient()
        profile = CompanyProfile.objects.get(pk=1)
        profile.data = {**profile.data, 'name': 'Moje podjetje', 'registration_number': OWN}
        profile.save()
        self.tender = Tender.objects.create(pk='suggest', data={
            'title': 'Vzdrževanje informacijskega sistema za evidenco pacientov', 'source_type': 'real', 'status': 'open',
            'cpv': ['72267000'], 'kind': 'services', 'description': 'Vzdrževanje in razvoj informacijskega sistema.'})
        award('pjn-1-1', [('Alfa d.o.o.', A)])
        award('pjn-2-1', [('Alfa d.o.o.', A), ('Beta d.o.o.', B)])
        award('pjn-3-1', [('Moje podjetje', OWN)])
        award('pjn-4-1', [('Brez številke d.o.o.', '')])
        award('pjn-5-1', [('Gama d.o.o.', '4444444000')], title='Dobava pisarniškega materiala', cpv=['30192000'],
              description='Papir in pisala.')

    def test_ranks_similar_winners_and_skips_own_and_unidentified(self):
        with patch('tenders.past_awards.vector_candidates', return_value=[]):
            result = suggestions(self.tender)
        numbers = [item['registration_number'] for item in result['items']]
        self.assertEqual(numbers, [A, B])
        alfa = result['items'][0]
        self.assertEqual(alfa['wins_count'], 2)
        self.assertEqual(alfa['joint_bids'], 1)
        self.assertEqual(alfa['total_value'], 200000.0)
        self.assertTrue(alfa['wins'][0]['notice_url'].startswith('https://www.enarocanje.si/'))
        self.assertIsNone(alfa['partner_id'])

    def test_reference_gaps_come_from_open_conditions(self):
        TenderConditions.objects.create(tender=self.tender, fingerprint='x', mode='live', extracted_at='2026-11-12T00:00Z', conditions=[
            {'id': 'c1', 'category': 'technical', 'title': 'Dve referenci', 'requirement': 'Ponudnik predloži dve referenci.',
             'quote': 'dve referenci', 'document_id': 'd', 'document_title': 'Pogoji', 'page': 1, 'locator': '', 'check': {'kind': 'none'}},
            {'id': 'c2', 'category': 'economic', 'title': 'Letni promet', 'requirement': 'Promet 1 milijon EUR.',
             'quote': 'promet', 'document_id': 'd', 'document_title': 'Pogoji', 'page': 1, 'locator': '', 'check': {'kind': 'none'}}])
        with patch('tenders.past_awards.vector_candidates', return_value=[]):
            self.assertEqual(suggestions(self.tender)['reference_gaps'], ['Dve referenci'])

    def test_add_creates_partner_with_public_references(self):
        url = '/api/tenders/suggest/partner-suggestions'
        with patch('tenders.ajpes.preview', side_effect=LookupError):
            response = self.client.post(url, {'registration_number': A}, format='json')
        self.assertEqual(response.status_code, 201)
        partner = Partner.objects.get(pk=response.data['id'])
        self.assertEqual(partner.source_type, 'real')
        self.assertEqual(partner.data['name'], 'Alfa d.o.o.')
        self.assertEqual(len(partner.data['references']), 2)
        self.assertTrue(all(r['confirmed'] and r['evidence_url'] for r in partner.data['references']))
        self.assertFalse(partner.data['capability_evidence']['confirmed'])
        # Already added: marked in suggestions and not added twice.
        with patch('tenders.past_awards.vector_candidates', return_value=[]):
            self.assertEqual(self.client.get(url).data['items'][0]['partner_id'], partner.pk)
        with patch('tenders.ajpes.preview', side_effect=LookupError):
            self.assertEqual(self.client.post(url, {'registration_number': A}, format='json').status_code, 400)

    def test_add_rejects_unknown_and_invalid_numbers(self):
        url = '/api/tenders/suggest/partner-suggestions'
        for number in ['9999999000', 'abc', None, OWN]:
            with patch('tenders.ajpes.preview', side_effect=LookupError):
                self.assertEqual(self.client.post(url, {'registration_number': number}, format='json').status_code, 400, number)

    def test_demo_tenders_get_no_suggestions(self):
        self.tender.data['source_type'] = 'demo'
        self.tender.save()
        self.assertEqual(suggestions(self.tender)['items'], [])

    def test_closed_tenders_get_no_suggestions(self):
        self.tender.data['status'] = 'closed'
        self.tender.save()
        self.assertEqual(suggestions(self.tender)['items'], [])
