from django.core.management.base import BaseCommand
from tenders.seed import ensure_seed
from tenders.models import Tender, Document
from tenders.past_awards import ensure_past_awards


class Command(BaseCommand):
    help = 'Pripravi izmišljeni demo profil, sedem razpisov in PDF dokumentacijo.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Ponastavi uporabniške demo spremembe.')

    def handle(self, *args, **options):
        ensure_seed(reset=options['reset'])
        ensure_past_awards()  # real public award notices, loaded once into an empty table
        self.stdout.write(self.style.SUCCESS(f'Demo je pripravljen: {Tender.objects.count()} razpisov, {Document.objects.count()} dokumentov.'))
