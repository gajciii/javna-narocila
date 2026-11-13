from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook

from .erar import award_payments, recipient_payments
from .models import ErarPayment, PastAward


class ErarImportTests(TestCase):
    def test_overlapping_excel_and_csv_exports_and_ambiguous_award(self):
        award_data = {'awarded': True, 'framework': False, 'notice_number': 'JN001234/2025-EUe29/01',
                      'buyer_registration_number': '1111111000',
                      'winners': [{'registration_number': '2222222000'}]}
        award = PastAward.objects.create(pk='pjn-10-1', notice_id='10', data=award_data)
        with TemporaryDirectory() as folder:
            book = Workbook()
            book.active.append(['Identifikator transakcije', 'Datum transakcije', 'Znesek transakcije (EUR)',
                                'Matična številka plačnika', 'Matična številka prejemnika', 'Številka JN',
                                'Oznaka valute transakcije (EUR)'])
            book.active.append(['test-1', date(2025, 10, 1), 120, '1111111000', '2222222000', 'JN001234/2025', 'EUR'])
            book.active.append(['test-2', date(2025, 10, 1), 50, '1111111000', '2222222000', '', 'EUR'])
            excel = Path(folder) / 'erar.xlsx'
            book.save(excel)
            call_command('import_erar', str(excel), exported_on='2025-10-02', verbosity=0)
            export = Path(folder) / 'erar.csv'
            export.write_text('ID transakcije;Datum transakcije;Znesek EUR\ntest-1;1. 10. 2025;130,50\n', encoding='utf-8-sig')
            call_command('import_erar', str(export), exported_on='2025-10-03', verbosity=0)
            call_command('import_erar', str(excel), exported_on='2025-10-02', verbosity=0)
        self.assertEqual(ErarPayment.objects.count(), 2)
        self.assertEqual(recipient_payments('2222222'), {'registration_number': '2222222000', 'payments': {
            'amount': Decimal('180.50'), 'count': 2, 'first_payment_on': date(2025, 10, 1),
            'latest_payment_on': date(2025, 10, 1), 'latest_export_on': date(2025, 10, 3),
        }})
        self.assertIsNone(recipient_payments('1111111')['payments'])
        self.assertEqual(award_payments(award), {'amount': 130.50, 'count': 1,
            'latest_export_on': '2025-10-03', 'latest_payment_on': '2025-10-01'})
        PastAward.objects.create(pk='pjn-10-2', notice_id='10', data=award_data)
        self.assertIsNone(award_payments(award))
