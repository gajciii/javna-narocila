import json
import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from tenders.pjn_sync import sync_recent, import_single
from tenders.seed import ensure_seed


class Command(BaseCommand):
    help = 'Zajame zadnje objave e-Naročanja; največ dva zagona dnevno.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--watch', action='store_true', help='Ponavlja zajem vsakih 12 ur, dokler proces teče.')
        parser.add_argument('--notice', help='ID ali URL posamezne objave namesto seznama.')

    def handle(self, *args, **options):
        ensure_seed()
        while True:
            try:
                if options['notice'] and options['watch']:
                    raise ValueError('--notice in --watch se ne uporabljata skupaj.')
                result = import_single(options['notice']) if options['notice'] else sync_recent(options['limit'])
                if 'tender' in result:
                    result['tender_id'] = result.pop('tender').id
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                if result['mode'] == 'unavailable' and not options['watch']:
                    raise CommandError(result['message'])
            except ValueError as exc:
                raise CommandError(str(exc))
            if not options['watch']:
                break
            close_old_connections()
            try:
                time.sleep(12 * 60 * 60)
            except KeyboardInterrupt:
                break
