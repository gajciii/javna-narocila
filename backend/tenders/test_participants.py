from django.test import TestCase
from .models import PastAward
from .participants import import_participants, participants
from .past_awards import serialize
from .deep_relevance import candidate_passages
from types import SimpleNamespace


class ParticipantTests(TestCase):
    def setUp(self):
        self.award = PastAward.objects.create(id='pjn-10-1', notice_id='10', data={
            'winners': [{'name': 'Izbrani d.o.o.', 'registration_number': '1111111'}]})

    def test_all_known_participants_and_distinct_outcomes(self):
        entries = [
            {'name': 'Drugi d.o.o.', 'registration_number': '2222222', 'outcome': 'not_selected',
             'source_url': 'https://ejn.gov.si/ponudba/record'},
            {'name': 'Tretji d.o.o.', 'registration_number': '3333333',
             'source_url': 'https://ejn.gov.si/ponudba/record'}]
        import_participants([{'award_id': self.award.pk, 'participants': entries}])
        self.award.refresh_from_db()
        payload = serialize(0.8, self.award)
        self.assertEqual([p['outcome'] for p in payload['participants']], ['winner', 'not_selected', 'unknown'])
        self.assertEqual(payload['participant_coverage'], 'partial_records')
        import_participants([{'award_id': self.award.pk, 'participants': entries}])
        self.award.refresh_from_db()
        self.assertEqual(len(participants(self.award)), 3)

    def test_missing_participant_list_is_not_claimed_complete(self):
        self.assertEqual(serialize(0.8, self.award)['participant_coverage'], 'winners_only')

    def test_untrusted_source_or_invented_winner_rejected(self):
        for outcome, source in [('winner', 'https://ejn.gov.si/record'), ('unknown', 'https://example.com')]:
            with self.assertRaises(ValueError):
                import_participants([{'award_id': self.award.pk, 'participants': [
                    {'name': 'Podjetje', 'outcome': outcome, 'source_url': source}]}])

    def test_attachment_search_uses_different_company_profiles(self):
        doc = SimpleNamespace(id='d', title='Popis.pdf', status='processed', extraction={}, pages=[
            {'page': 1, 'text': 'Dobava kirurških instrumentov za bolnišnico.'},
            {'page': 2, 'text': 'Tiskanje brošur in plakatov za otvoritev.'}])
        for term, expected in [('kirurški instrumenti', 1), ('tiskanje brošur', 2)]:
            found, _ = candidate_passages([doc], {'activity': term})
            self.assertEqual({p['page'] for p in found}, {expected})
