import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tenders.past_awards import import_notices


class Command(BaseCommand):
    help = ('Uvozi obvestila o oddaji s Portala javnih naročil (JSON seznam zapisov, npr. izvoz Apify '
            'strgalnika publicmoney/enarocanje-slovenia-scraper s phase=RESULT). Obstoječe oddaje se posodobijo.')

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='+', help='Pot do JSON datoteke s seznamom obvestil.')

    def handle(self, *args, **options):
        for name in options['files']:
            path = Path(name)
            try:
                records = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise CommandError(f'{path}: datoteke ni mogoče prebrati ({type(exc).__name__}).')
            if not isinstance(records, list):
                raise CommandError(f'{path}: pričakovan je seznam obvestil.')
            result = import_notices(records)
            self.stdout.write(f"{path.name}: {result['notices']} obvestil, {result['lots']} sklopov "
                              f"({result['created']} novih, {result['updated']} posodobljenih).")
