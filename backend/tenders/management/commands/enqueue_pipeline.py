import time
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import close_old_connections

from tenders.pipeline_runs import create_run, claim_run, collect_run, register_agent, beat_agent


class Command(BaseCommand):
    help = 'Zajame nove metapodatke in naroči skupno indeksiranje brez profila podjetja.'

    def add_arguments(self, parser):
        parser.add_argument('--period', help='YYYY-MM; privzeto trenutni mesec.')
        parser.add_argument('--existing', action='store_true', help='Samo že shranjeni razpisi, brez dostopa do PJN.')
        parser.add_argument('--max-notices', type=int)
        parser.add_argument('--watch', action='store_true', help='Ponovi vsakih 24 ur.')

    def handle(self, *args, **options):
        if options['max_notices'] is not None and options['max_notices'] < 1:
            raise CommandError('--max-notices mora biti pozitiven.')
        if options['watch'] and (options['existing'] or options['period'] or options['max_notices']):
            raise CommandError('--watch upravlja dnevni urnik in ročne zahteve iz portala; posebni zagon izvedite brez --watch.')
        requested = None
        if not options['watch']:
            try:
                requested = create_run(source='cli', mode='existing' if options['existing'] else 'monthly',
                    period=options['period'] or '', max_notices=options['max_notices'])
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        agent = register_agent('scheduler')
        last_beat = 0
        try:
            while True:
                close_old_connections()
                run = claim_run(schedule=options['watch'])
                if run:
                    collect_run(run, agent)
                    self.stdout.write(f'run={run.pk} state={run.state} listed={run.listed_count} jobs={run.jobs.count()}')
                    self.stdout.flush()
                if not options['watch'] and (run is None or run.pk == requested.pk):
                    self.stdout.write(f'Zahtevani zagon: {requested.pk}.')
                    return
                if time.monotonic() - last_beat >= 15:
                    beat_agent(agent)
                    last_beat = time.monotonic()
                if not run:
                    time.sleep(3)
        finally:
            beat_agent(agent, 'stopped')
