from django.core.management.base import BaseCommand, CommandError

from tenders.past_awards import BUNDLE, ensure_past_awards, import_notices, read_json, write_bundle


class Command(BaseCommand):
    help = ('Uvozi obvestila o oddaji s Portala javnih naročil (JSON ali JSON.gz seznam zapisov, npr. izvoz Apify '
            'strgalnika publicmoney/enarocanje-slovenia-scraper s phase=RESULT). Obstoječe oddaje se posodobijo. '
            'Brez datotek naloži priloženo zbirko, če je tabela prazna.')

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='*', help='Pot do JSON ali JSON.gz datoteke s seznamom obvestil.')
        parser.add_argument('--write-bundle', action='store_true',
                            help=f'Po uvozu zapiše celotno tabelo v {BUNDLE.relative_to(BUNDLE.parents[2])} za Git.')

    def handle(self, *args, **options):
        if not options['files']:
            loaded = ensure_past_awards()
            self.stdout.write(f'Naloženih {loaded} sklopov iz priložene zbirke.' if loaded else 'Tabela že vsebuje oddaje; nič ni bilo naloženo.')
        for name in options['files']:
            try:
                records = read_json(name)
            except (OSError, ValueError) as exc:
                raise CommandError(f'{name}: datoteke ni mogoče prebrati ({type(exc).__name__}).')
            if not isinstance(records, list):
                raise CommandError(f'{name}: pričakovan je seznam obvestil.')
            result = import_notices(records)
            self.stdout.write(f"{name}: {result['notices']} obvestil, {result['lots']} sklopov "
                              f"({result['created']} novih, {result['updated']} posodobljenih).")
        if options['write_bundle']:
            self.stdout.write(f'Zapisanih {write_bundle()} sklopov v {BUNDLE}.')
