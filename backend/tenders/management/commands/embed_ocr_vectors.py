import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection
from django.db.models import Max

from tenders import embeddings
from tenders.models import DocumentChunk
from tenders.ocr_embeddings import embed_ocr_batch, ocr_chunks
from tenders.ocr_policy import OCR_IMPORT_VERSION


class Command(BaseCommand):
    help = 'Izrecno izdela samo manjkajoče OCR embeddinge prek plačljivega API-ja; ostale vektorje ohrani.'

    def add_arguments(self, parser):
        parser.add_argument('--status', action='store_true', help='Samo prešteje, brez API klicev.')
        parser.add_argument('--batch-size', type=int, default=embeddings.BATCH)
        parser.add_argument('--max-batches', type=int, default=0, help='0 pomeni do zaključka ciljne vrste.')
        parser.add_argument('--through-pk', type=int, help='Omeji zagon na obstoječi posnetek odlomkov.')
        parser.add_argument('--workers', type=int, default=1, help='Sočasni API paketi (1–4).')
        parser.add_argument('--report', help='Pot za sprotno JSON poročilo.')

    def handle(self, *args, **options):
        if not 1 <= options['batch_size'] <= embeddings.BATCH or options['max_batches'] < 0:
            raise CommandError('Neveljavna velikost ali število paketov.')
        if options['through_pk'] is not None and options['through_pk'] < 1:
            raise CommandError('--through-pk mora biti pozitiven.')
        if not 1 <= options['workers'] <= 4:
            raise CommandError('--workers mora biti med 1 in 4.')
        maximum = ocr_chunks().aggregate(value=Max('pk'))['value']
        if maximum is not None and options['through_pk'] is not None:
            maximum = min(maximum, options['through_pk'])
        target = ocr_chunks(maximum) if maximum is not None else ocr_chunks().none()
        total = target.count()
        initial_missing = target.filter(embedding__isnull=True).count()
        report = {'state': 'status' if options['status'] else 'running', 'version': OCR_IMPORT_VERSION,
                  'model': embeddings.MODEL, 'total': total, 'initial_missing': initial_missing,
                  'already_embedded': total-initial_missing, 'maximum_pk': maximum, 'batches': 0}

        def progress(state=None):
            if state:
                report['state'] = state
            remaining = target.filter(embedding__isnull=True).count()
            rejected = list(target.filter(embedding__isnull=True,
                pk__in=embeddings._rejected[DocumentChunk]).values_list('pk', flat=True))
            report.update(remaining=remaining, embedded_this_run=initial_missing-remaining,
                          rejected_ids=rejected, updated_at=time.time())
            if options['report']:
                path = Path(options['report'])
                tmp = path.with_suffix('.tmp')
                tmp.write_text(json.dumps(report))
                tmp.replace(path)

        progress()
        if options['status']:
            self.stdout.write(json.dumps(report))
            return
        if not embeddings.enabled():
            raise CommandError('OCR embeddingi zahtevajo PostgreSQL in OPENROUTER_API_KEY.')
        mutex, cancelled = threading.Lock(), threading.Event()
        reserved = 0

        def worker():
            nonlocal reserved
            if options['workers'] > 1:
                close_old_connections()
            try:
                while initial_missing and not cancelled.is_set():
                    with mutex:
                        if options['max_batches'] and reserved >= options['max_batches']:
                            return
                        reserved += 1
                    done = embed_ocr_batch(options['batch_size'], maximum_pk=maximum)
                    if not done:
                        with mutex:
                            reserved -= 1
                        # Another explicit worker may currently hold the last missing rows.
                        if target.filter(embedding__isnull=True).exclude(
                                pk__in=embeddings._rejected[DocumentChunk]).exists():
                            time.sleep(1)
                            continue
                        return
                    with mutex:
                        report['batches'] += 1
                        progress()
                        self.stdout.write(json.dumps(report))
                        self.stdout.flush()
            except Exception:
                cancelled.set()
                raise
            finally:
                if options['workers'] > 1:
                    connection.close()

        try:
            if options['workers'] == 1:
                worker()
            else:
                with ThreadPoolExecutor(max_workers=options['workers']) as pool:
                    list(pool.map(lambda _: worker(), range(options['workers'])))
            progress('complete' if target.filter(embedding__isnull=True).count() == 0 else 'incomplete')
            self.stdout.write(json.dumps(report))
            if report['remaining'] and not options['max_batches']:
                raise CommandError(f"OCR odlomki brez vektorjev: {report['remaining']}; glejte poročilo.")
        except Exception:
            progress('failed')
            raise
