import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from tenders.pjn_sync import sync_awards


class Command(BaseCommand):
    help = ('Prenese manjkajoča obvestila o oddaji (faza "Rezultat") neposredno s Portala javnih naročil v tabelo '
            'preteklih oddaj. Brez --from nadaljuje od najnovejše shranjene oddaje; z --from/--to zapolni starejše obdobje.')

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='since', help='Prvi dan objave (YYYY-MM-DD).')
        parser.add_argument('--to', dest='until', help='Zadnji dan objave (YYYY-MM-DD); privzeto danes.')
        parser.add_argument('--max-notices', type=int, help='Največ prenesenih obvestil v tem zagonu.')
        parser.add_argument('--delay', type=float, default=0.3, help='Premor med zahtevki v sekundah.')

    def handle(self, *args, **options):
        try:
            since = date.fromisoformat(options['since']) if options['since'] else None
            until = date.fromisoformat(options['until']) if options['until'] else None
        except ValueError as exc:
            raise CommandError('Datum mora biti v obliki YYYY-MM-DD.') from exc
        if options['max_notices'] is not None and options['max_notices'] < 1:
            raise CommandError('--max-notices mora biti pozitiven.')
        if options['delay'] < 0:
            raise CommandError('--delay ne sme biti negativen.')
        try:
            result = sync_awards(since, until, options['max_notices'], options['delay'])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result['errors'] = result['errors'][:20]
        self.stdout.write(json.dumps(result, ensure_ascii=False))
