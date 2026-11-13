"""Import public ERAR exports and attribute payments to historical award lots."""
import csv
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile

from django.db import transaction
from django.db.models import Count, Max, Min, Sum

from .ajpes import optional_registration_number
from .models import ErarPayment, PastAward

LIMIT = 20 * 1024 * 1024
PROCEDURE = re.compile(r'\bJN[0-9]+/[0-9]{4}\b', re.IGNORECASE)
FIELDS = {
    'source_id': ('id transakcije', 'identifikator transakcije', 'enolicni identifikator transakcije', 'id'),
    'paid_on': ('datum transakcije', 'datum placila', 'datum izvrsitve', 'datum'),
    'amount': ('znesek transakcije eur', 'znesek eur', 'znesek', 'znesek transakcije'),
    'currency': ('oznaka valute transakcije eur', 'valuta', 'oznaka valute'),
    'payer': ('maticna stevilka placnika', 'ms placnika', 'maticna placnika'),
    'recipient': ('maticna stevilka prejemnika', 'ms prejemnika', 'maticna prejemnika'),
    'procedure': ('stevilka jn', 'stevilka javnega narocila', 'narocilo'),
    'award_id': ('id sklopa pjn',),
}


def header(value):
    chars = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in chars if not unicodedata.combining(c))))


def rows(path):
    if path.stat().st_size > LIMIT:
        raise ValueError('Datoteka presega 20 MB. Izvoz omejite po obdobju ali prejemniku.')
    if path.suffix.lower() == '.xlsx':
        from openpyxl import load_workbook
        with ZipFile(path) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 5 * LIMIT:
                raise ValueError('Razpakirana datoteka Excel je prevelika.')
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            yield from workbook.worksheets[0].iter_rows(values_only=True)
        finally:
            workbook.close()
    elif path.suffix.lower() == '.csv':
        raw = path.read_bytes()
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = raw.decode('cp1250')
        first = next((line for line in content.splitlines() if line.strip()), '')
        dialect = csv.Sniffer().sniff(first, delimiters=';,\t')
        yield from csv.reader(io.StringIO(content), dialect)
    else:
        raise ValueError('Uporabite izvoz CSV ali XLSX.')


def identifier(value):
    return optional_registration_number(str(value or ''))


def paid_date(value):
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if re.fullmatch(r'\d{1,2}\.\s*\d{1,2}\.\s*\d{4}', text):
        return datetime.strptime(text.replace(' ', ''), '%d.%m.%Y').date()
    return date.fromisoformat(text)


def payment_amount(value):
    text = re.sub(r'\s+', '', str(value)).removesuffix('€')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    amount = Decimal(text)
    if not amount.is_finite() or abs(amount) >= 10 ** 16 or amount != amount.quantize(Decimal('0.01')):
        raise ValueError('Neveljaven znesek.')
    return amount


def import_export(filename, exported_on):
    records = {}
    columns = None
    for line, cells in enumerate(rows(Path(filename)), 1):
        if not any(cell is not None and cell != '' for cell in cells):
            continue
        if columns is None:
            headings = [header(cell) for cell in cells]
            columns = {}
            for key, aliases in FIELDS.items():
                label = next((alias for alias in (key.replace('_', ' '), *aliases) if alias in headings), None)
                if label:
                    columns[key] = headings.index(label)
            if not {'source_id', 'paid_on', 'amount'} <= columns.keys():
                raise ValueError('Manjkajo stolpci ID transakcije, datum in znesek.')
            if 'currency' not in columns and headings[columns['amount']] not in ('znesek eur', 'znesek transakcije eur'):
                raise ValueError('Dodajte stolpec Valuta ali uporabite naslov Znesek EUR.')
            continue

        def cell(field):
            index = columns.get(field, len(cells))
            return cells[index] if index < len(cells) else None

        try:
            source_id = str(cell('source_id') or '').strip()
            currency = 'EUR' if 'currency' not in columns else str(cell('currency') or '').strip().upper()
            if not source_id or len(source_id) > 120 or not re.fullmatch(r'[A-Z]{3}', currency):
                raise ValueError
            paid_on = paid_date(cell('paid_on'))
            if paid_on > exported_on:
                raise ValueError
            reference = PROCEDURE.fullmatch(str(cell('procedure') or '').strip())
            award_id = str(cell('award_id') or '').strip()
            if len(award_id) > 80 or (award_id and not re.fullmatch(r'pjn-[0-9]+-[0-9]+', award_id)):
                raise ValueError
            if reference and len(reference[0]) > 30:
                raise ValueError
            record = {'paid_on': paid_on, 'amount': payment_amount(cell('amount')), 'currency': currency,
                      'payer': identifier(cell('payer')), 'recipient': identifier(cell('recipient')),
                      'procedure': reference[0].upper() if reference else '', 'award_id': award_id,
                      'exported_on': exported_on}
            if source_id in records and records[source_id] != record:
                raise ValueError
            records[source_id] = record
        except (ValueError, InvalidOperation, TypeError) as exc:
            raise ValueError(f'Vrstica {line} vsebuje neveljavno ali nasprotujočo si transakcijo.') from exc
    if columns is None:
        raise ValueError('Izvoz je prazen.')
    with transaction.atomic():
        # Corrections from a newer export replace earlier versions of the same ERAR ID.
        for source_id, record in records.items():
            payment, created = ErarPayment.objects.get_or_create(source_id=source_id, defaults=record)
            if not created:
                updates = {key: value for key, value in record.items()
                           if key not in ('award_id', 'procedure', 'payer', 'recipient') or key in columns}
                ErarPayment.objects.filter(pk=payment.pk, exported_on__lte=exported_on).update(**updates)
    return len(records)


def recipient_payments(number_input):
    recipient = identifier(number_input)
    result = {'registration_number': recipient, 'payments': None}
    if not recipient:
        return result
    totals = ErarPayment.objects.filter(recipient=recipient, currency='EUR').aggregate(
        amount=Sum('amount'), count=Count('pk'), first_payment_on=Min('paid_on'),
        latest_payment_on=Max('paid_on'), latest_export_on=Max('exported_on'),
    )
    if totals['count']:
        result['payments'] = totals
    return result


def award_payments(award):
    from .past_awards import procedure_number

    if not award.data.get('awarded') or award.data.get('framework'):
        return None
    procedure = procedure_number(award.data.get('notice_number'))
    buyer = identifier(award.data.get('buyer_registration_number'))
    winners = {identifier(winner.get('registration_number')) for winner in award.data.get('winners') or []} - {''}
    direct = ErarPayment.objects.filter(award_id=award.pk, currency='EUR')
    payments = [item for item in direct if (not item.payer or not buyer or item.payer == buyer)
                and (not item.recipient or not winners or item.recipient in winners)
                and (not item.procedure or item.procedure == procedure)]
    if procedure and buyer and winners:
        candidates = list(ErarPayment.objects.filter(procedure=procedure, award_id='', currency='EUR',
                                                     payer=buyer, recipient__in=winners))
        if candidates:
            other_recipients = set()
            for other in PastAward.objects.filter(data__notice_number__startswith=procedure,
                                                   data__awarded=True).exclude(pk=award.pk):
                if (procedure_number(other.data.get('notice_number')) == procedure
                        and identifier(other.data.get('buyer_registration_number')) in ('', buyer)):
                    other_recipients.update(identifier(w.get('registration_number')) for w in other.data.get('winners') or [])
            payments.extend(item for item in candidates if item.recipient not in other_recipients)
    if not payments:
        return None
    return {'amount': float(sum(item.amount for item in payments)), 'count': len(payments),
            'latest_export_on': max(item.exported_on for item in payments).isoformat(),
            'latest_payment_on': max(item.paid_on for item in payments).isoformat()}
