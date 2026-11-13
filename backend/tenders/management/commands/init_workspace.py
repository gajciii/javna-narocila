from django.core.management.base import BaseCommand

from tenders.past_awards import ensure_past_awards
from tenders.seed import ensure_seed
from tenders.runtime_data import application_tenders


class Command(BaseCommand):
    help = 'Pripravi prazen profil in naloži shranjeno zbirko resničnih preteklih oddaj.'

    def handle(self, *args, **options):
        ensure_seed()
        ensure_past_awards()
        self.stdout.write(self.style.SUCCESS(
            f'Okolje je pripravljeno: {application_tenders().count()} resničnih razpisov.'))
