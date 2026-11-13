import csv
from datetime import date
from zipfile import BadZipFile

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from openpyxl.utils.exceptions import InvalidFileException

from tenders.erar import import_export


def load_export(filename, export_date):
    try:
        exported_on = date.fromisoformat(export_date)
        if exported_on > timezone.localdate():
            raise ValueError('Datum izvoza ne sme biti v prihodnosti.')
        return import_export(filename, exported_on)
    except (ValueError, OSError, csv.Error, BadZipFile, InvalidFileException) as exc:
        raise CommandError(f'Uvoz ERAR ni uspel. {exc}') from exc


class Command(BaseCommand):
    help = 'Uvozi transakcije iz izvoza ERAR CSV ali XLSX.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--exported-on', required=True, help='Datum izvoza v obliki YYYY-MM-DD.')

    def handle(self, *args, **options):
        count = load_export(options['file'], options['exported_on'])
        self.stdout.write(f'Obdelanih transakcij ERAR: {count}.')
