import logging
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection

from tenders.analytics import capture
from tenders.embeddings import embed_pending
from tenders.pipeline_jobs import claim, execute, renew
from tenders.pipeline_runs import register_agent, beat_agent


class Command(BaseCommand):
    help = 'Obdeluje skupno PostgreSQL vrsto za indeksiranje in presojo prilog.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Obdela največ eno opravilo.')
        parser.add_argument('--poll', type=float, default=3)

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql' or not settings.PIPELINE_S3_ENDPOINT:
            raise CommandError('Ločeni delavec zahteva PostgreSQL in skupno S3 shrambo.')
        if options['poll'] < 0.1:
            raise CommandError('--poll mora biti vsaj 0.1.')
        agent = register_agent('worker')
        last_beat = 0
        embed_after = 0
        try:
            while True:
                close_old_connections()
                job = claim(worker=f'{agent.hostname}/{str(agent.pk)[:8]}')
                if job:
                    stop = threading.Event()
                    beat_agent(agent, 'working', job_id=job.pk)

                    def heartbeat():
                        close_old_connections()
                        try:
                            while not stop.wait(30):
                                if not renew(job):
                                    return
                                beat_agent(agent, 'working', job_id=job.pk)
                        finally:
                            connection.close()

                    thread = threading.Thread(target=heartbeat, daemon=True)
                    thread.start()
                    try:
                        execute(job)
                        job.refresh_from_db()
                        self.stdout.write(f'job={job.pk} kind={job.kind} state={job.state}', ending='\n')
                        self.stdout.flush()
                    finally:
                        stop.set()
                        thread.join(timeout=5)
                        beat_agent(agent)
                if options['once']:
                    return
                if time.monotonic() - last_beat >= 15:
                    beat_agent(agent)
                    last_beat = time.monotonic()
                if not job and time.monotonic() >= embed_after:
                    # Idle time fills semantic vectors; jobs always come first.
                    try:
                        filled = embed_pending()
                    except Exception as exc:
                        logging.getLogger(__name__).warning('Embedding batch failed: %s', type(exc).__name__)
                        capture('embedding_batch_failed', error=type(exc).__name__)
                        filled = 0
                        embed_after = time.monotonic() + 120
                    else:
                        embed_after = 0 if filled else time.monotonic() + 300
                    if filled:
                        continue
                if not job:
                    time.sleep(options['poll'])
        finally:
            beat_agent(agent, 'stopped')
