import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from tenders.pjn_contracts import sync_contract_list


class Command(BaseCommand):
    help = ('Prenese objavljene pogodbe in anekse s Portala javnih naročil v register pogodb. Brez --from nadaljuje '
            'od zadnjega zaključenega dne; z --from/--to zapolni starejše obdobje po mesecih. Že shranjene pogodbe '
            'preskoči, zato je prekinjen zagon mogoče ponoviti.')

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='since', help='Prvi dan objave (YYYY-MM-DD).')
        parser.add_argument('--to', dest='until', help='Zadnji dan objave (YYYY-MM-DD); privzeto danes.')
        parser.add_argument('--max-contracts', type=int, help='Največ prenesenih pogodb na mesec v tem zagonu.')
        parser.add_argument('--workers', type=int, default=4, help='Vzporedni prenosi (1-16); privzeto 4.')
        parser.add_argument('--rate', type=float, default=5.0,
                            help='Največ zahtevkov na sekundo skupaj za vse prenose (do 50); privzeto 5.')

    def handle(self, *args, **options):
        try:
            since = date.fromisoformat(options['since']) if options['since'] else None
            until = date.fromisoformat(options['until']) if options['until'] else date.today()
        except ValueError as exc:
            raise CommandError('Datum mora biti v obliki YYYY-MM-DD.') from exc
        if options['max_contracts'] is not None and options['max_contracts'] < 1:
            raise CommandError('--max-contracts mora biti pozitiven.')
        if not 1 <= options['workers'] <= 16 or not 0 < options['rate'] <= 50:
            raise CommandError('--workers mora biti od 1 do 16, --rate večji od 0 in največ 50.')
        if since and since > until:
            raise CommandError('Začetek obdobja je po koncu.')
        windows = []
        while since and since <= until:
            # Month windows keep each listing short and show progress during a long backfill.
            end = min(until, (since.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
            windows.append((since, end))
            since = end + timedelta(days=1)
        for start, end in windows or [(None, options['until'] and until)]:
            try:
                result = sync_contract_list(start, end, options['max_contracts'],
                                            workers=options['workers'], rate=options['rate'])
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            result['errors'] = result['errors'][:20]
            self.stdout.write(json.dumps(result, ensure_ascii=False))
