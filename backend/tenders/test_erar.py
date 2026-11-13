from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook

from .erar import award_payments, recipient_payments, tender_payments
from .models import ErarPayment, PastAward, Tender


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


class TenderPaymentTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(pk='pjn-dosje-10', data={
            'source_type': 'real', 'source_metadata': {'notice_id': '100', 'dossier_id': 10}})
        self.award_data = {'awarded': True, 'framework': False, 'notice_number': 'JN001234/2025-SL2/01',
                           'buyer_registration_number': '1111111000', 'lot_title': 'Prvi sklop',
                           'winners': [{'registration_number': '2222222000'}]}
        self.award = PastAward.objects.create(pk='pjn-100-1', notice_id='100', dossier_id='10', data=self.award_data)
        ErarPayment.objects.create(source_id='paid', award_id=self.award.pk, currency='EUR',
                                   amount='123.45', paid_on=date(2025, 10, 1), exported_on=date(2025, 10, 2))
        # General company turnover has no evidence connecting it to this award.
        ErarPayment.objects.create(source_id='unattributed', currency='EUR', recipient='2222222000',
                                   amount='999', paid_on=date(2025, 10, 1), exported_on=date(2025, 10, 2))

    def test_shows_attributed_payments_only_for_exact_notice_and_dossier(self):
        self.assertEqual(tender_payments(self.tender), [{
            'award_id': 'pjn-100-1', 'lot_title': 'Prvi sklop', 'amount': 123.45, 'count': 1,
            'latest_payment_on': '2025-10-01', 'latest_export_on': '2025-10-02'}])
        self.tender.data['source_metadata']['notice_id'] = '101'
        self.assertEqual(tender_payments(self.tender), [])
        self.tender.data['source_metadata'] = {'notice_id': '100', 'dossier_id': 11}
        self.assertEqual(tender_payments(self.tender), [])

    def test_missing_data_and_frameworks_are_not_claimed_as_paid(self):
        self.award.data['framework'] = True
        self.award.save()
        self.assertEqual(tender_payments(self.tender), [])
        self.award.data['framework'] = False
        self.award.save()
        ErarPayment.objects.filter(pk='paid').delete()
        self.assertEqual(tender_payments(self.tender), [])
        self.tender.data['source_metadata'] = {}
        self.assertEqual(tender_payments(self.tender), [])

    def test_keeps_lot_amounts_separate(self):
        second = PastAward.objects.create(pk='pjn-100-2', notice_id='100', dossier_id='10',
                                         data={**self.award_data, 'lot_title': 'Drugi sklop'})
        ErarPayment.objects.create(source_id='paid-second', award_id=second.pk, currency='EUR',
                                   amount='0', paid_on=date(2025, 10, 2), exported_on=date(2025, 10, 3))
        rows = tender_payments(self.tender)
        self.assertEqual(len(rows), 2)
        self.assertEqual([row['amount'] for row in rows], [123.45, 0])
        self.assertEqual(rows[1]['lot_title'], 'Drugi sklop')
