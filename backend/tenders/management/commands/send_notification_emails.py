import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from tenders.email_notifications import process


class Command(BaseCommand):
    help = 'Pošlje nova e-poštna obvestila in ponovi neuspele poskuse; --watch preverja vsakih 15 sekund.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        try:
            while True:
                close_old_connections()
                sent = process()
                if sent:
                    self.stdout.write(f'Poslanih obvestil: {sent}')
                    self.stdout.flush()
                if not options['watch']:
                    return
                time.sleep(15)
        except KeyboardInterrupt:
            return
