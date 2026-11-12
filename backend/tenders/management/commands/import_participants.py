from django.core.management.base import BaseCommand, CommandError
from tenders.models import PastAward
from tenders.participants import import_participants
from tenders.past_awards import read_json


class Command(BaseCommand):
    help = 'Uvozi ponudnike iz strukturiranega javnega zapisnika; vsak zapis je vezan na točen award_id/sklop.'

    def add_arguments(self, parser):
        parser.add_argument('file')

    def handle(self, *args, **options):
        try:
            count = import_participants(read_json(options['file']))
        except (OSError, ValueError, TypeError, PastAward.DoesNotExist) as exc:
            raise CommandError(f'Uvoz ni uspel: {exc}') from exc
        self.stdout.write(f'Posodobljenih sklopov: {count}.')
