"""Resumable November 2026 notice and attachment scan with evidence-based findings."""
import hashlib
import csv
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from django.utils import timezone

from .deep_extract import process_document
from .deep_relevance import analyse, document_fingerprint
from .models import MonthlyScanItem
from .past_awards import ensure_past_awards
from .pjn_documents import download_documents
from .pjn_normalize import timestamp
from .pjn_sync import collect_notice
from .pjn_transport import fetch_json
from .relevance import settings as gemini_settings
from .seed import ensure_seed, get_profile

PERIOD = '2026-11'
PAGE_SIZE = 100
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_EXPANDED = 250 * 1024 * 1024


def month_dates(period):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period):
        raise ValueError('Mesec mora biti v obliki YYYY-MM.')
    year, month = map(int, period.split('-'))
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    if start > timezone.localdate():
        raise ValueError('Zajem prihodnjega meseca še ni mogoč.')
    return start, end


def grid_rows(period):
    for row in grid_entries(period):
        yield str(row['idObrazec'])


def grid_entries(period):
    """Grid rows of every notice published in the month; each has ``idObrazec`` and the procedure phase."""
    start, end = month_dates(period)
    seen, offset = set(), 0
    while True:
        body = {'startRow': offset, 'endRow': offset + PAGE_SIZE, 'page': offset // PAGE_SIZE + 1,
                'search': '', 'idSifCpv': [], 'idSifPostopekFaza': [], 'podrejeniCpv': True,
                'objavaDejanskaDatumOd': start.isoformat() + 'T00:00:00',
                'objavaDejanskaDatumDo': end.isoformat() + 'T00:00:00',
                'sortModel': [{'colId': 'objavaDejanskaDatum', 'sort': 'asc'}]}
        grid = fetch_json('obrazec/objava/obrazecGetGrid', body)
        rows = grid.get('data') if isinstance(grid, dict) else None
        total = grid.get('lastRow') if isinstance(grid, dict) else None
        if not isinstance(rows, list) or not isinstance(total, int) or total < 0:
            raise ValueError('Seznam objav nima pričakovane oblike.')
        if not rows and offset < total:
            raise ValueError('Portal je vrnil prazno stran pred koncem seznama.')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('idObrazec'), int):
                raise ValueError('Seznam vsebuje objavo brez veljavnega ID-ja.')
            published = timestamp(row.get('objavaDejanskaDatum'))
            if not published or not start <= published.date() < end:
                raise ValueError('Seznam vsebuje objavo z neveljavnim datumom za izbrani mesec.')
            notice_id = str(row['idObrazec'])
            if notice_id in seen:
                raise ValueError('Seznam vsebuje podvojeno objavo; preverite premik strani med zajemom.')
            seen.add(notice_id)
            yield row
        offset += len(rows)
        if offset >= total:
            break


def profile_fingerprint(profile, extra_terms, model, ai_enabled):
    capabilities = [profile.get(field) for field in ('activity', 'description', 'expertise', 'keywords', 'technologies')]
    value = [capabilities, extra_terms, model, ai_enabled, 'monthly-scan-v3']
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def scan_notice(period, notice_id, profile, fingerprint, extra_terms, ai_budget, require_ai=False):
    item, _ = MonthlyScanItem.objects.get_or_create(period=period, notice_id=notice_id)
    collected = collect_notice(notice_id, download=False)
    if collected['mode'] != 'live':
        item.state = 'error'
        item.result = {'notice_id': notice_id, 'error': collected.get('warning') or collected.get('message')}
        item.fingerprint = fingerprint
        item.save(update_fields=['state', 'result', 'fingerprint', 'updated_at'])
        return item
    tender = collected['tender']
    latest_notice = str(tender.data.get('source_metadata', {}).get('notice_id') or '')
    if latest_notice != notice_id:
        item.tender = tender
        item.fingerprint = fingerprint
        item.state = 'superseded'
        item.result = {'notice_id': notice_id, 'tender_id': tender.pk,
                       'source_url': f'https://www.enarocanje.si/#/pregled-objav/{notice_id}',
                       'superseded_by': latest_notice,
                       'warning': 'V bazi je novejša objava istega dosjeja; starejše priloge niso pripisane tej različici.'}
        item.save(update_fields=['tender', 'fingerprint', 'state', 'result', 'updated_at'])
        return item
    existing = tender.document_records.filter(version=tender.data['version']).exists()
    if existing and tender.data.get('source_metadata', {}).get('attachments_processed'):
        download = {'downloaded': 0}
    else:
        download = download_documents(tender, max_file=MAX_ARCHIVE, max_expanded=MAX_EXPANDED, max_members=200)
    documents = list(tender.document_records.filter(version=tender.data['version']).order_by('id'))
    for document in documents:
        process_document(document)
    readable = [d for d in documents if d.status == 'processed' and d.pages]
    unresolved = [{'document_id': d.id, 'title': d.title, 'error': d.error or 'Besedila ni bilo mogoče prebrati.'}
                  for d in documents if d.status != 'processed' or (not d.pages and d.extraction.get('mode') != 'archive')]
    if documents and not readable and not unresolved:
        unresolved.append({'document_id': None, 'title': 'Dokumentacija', 'error': 'Arhiv ne vsebuje berljivih prilog.'})
    if not documents and tender.data.get('source_metadata', {}).get('attachment_url'):
        unresolved.append({'document_id': None, 'title': 'Dokumentacija',
                           'error': download.get('warning') or 'Prilog ni bilo mogoče prenesti.'})
    analysis = analyse(tender, readable, profile, extra_terms, ai_budget)
    meta = dict(tender.data.get('source_metadata', {}))
    meta['attachments_processed'] = bool(documents) and not unresolved
    tender.data = {**tender.data, 'source_metadata': meta}
    tender.save(update_fields=['data'])
    source_missing = not meta.get('attachment_url')
    item.tender = tender
    item.fingerprint = fingerprint
    item.state = 'partial' if source_missing or unresolved or (require_ai and analysis['ai_pending']) else 'complete'
    item.result = {'notice_id': notice_id, 'tender_id': tender.pk, 'title': tender.data.get('title'),
                   'source_url': tender.data.get('source_url'), 'published_at': tender.data.get('published_at'),
                   'status': tender.data.get('status'), 'version': tender.data['version'],
                   'downloaded': download.get('downloaded', 0), 'documents': len(documents),
                   'readable_documents': len(readable), 'unresolved_documents': unresolved,
                   'documents_fingerprint': document_fingerprint(readable),
                   'documentation_warning': download.get('warning') if source_missing or unresolved else None,
                   **analysis}
    item.save(update_fields=['tender', 'fingerprint', 'state', 'result', 'updated_at'])
    return item


def write_report(period, path, listed, limited):
    rows = list(MonthlyScanItem.objects.filter(period=period).select_related('tender').order_by('notice_id'))
    notices = []
    for row in rows:
        latest = (row.tender.data.get('source_metadata') or {}).get('notice_id') if row.tender else None
        notices.append({**row.result, 'state': row.state, 'superseded': bool(latest and latest != row.notice_id)})
    report = {'period': period, 'generated_at': timezone.now().isoformat(),
              'month_complete': timezone.localdate() >= month_dates(period)[1],
              'listing_count': listed, 'limited_run': limited, 'scanned_count': len(rows),
              'complete_count': sum(r.state == 'complete' for r in rows),
              'superseded_count': sum(r.state == 'superseded' for r in rows),
              'partial_count': sum(r.state == 'partial' for r in rows),
              'error_count': sum(r.state == 'error' for r in rows),
              'findings_count': sum(len(r.result.get('findings', [])) for r in rows),
              'notes': ['Ponudniki so označeni po izidu in viru. Seznam vsebuje znane zmagovalce in dodatne uvožene zapisnike; ni nujno popoln.',
                        'Kandidat za dobavo ali podizvajanje ni dokaz, da bo glavni izvajalec iskal partnerja.',
                        'Neprebrane ali zunanje priloge so navedene kot neobdelane.'],
              'notices': notices}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    csv_path = path.with_suffix('.csv')
    fields = ['notice_id', 'title', 'state', 'superseded', 'kind', 'confidence', 'document_title',
              'location', 'quote', 'source_url', 'historical_participants']

    def safe(value):
        value = str(value if value is not None else '')
        return "'" + value if value.startswith(('=', '+', '-', '@')) else value

    with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for notice in notices:
            for finding in notice.get('findings', []):
                writer.writerow({k: safe(v) for k, v in {
                    'notice_id': notice['notice_id'], 'title': notice.get('title'), 'state': notice['state'],
                    'superseded': notice['superseded'], 'kind': finding['kind'], 'confidence': finding['confidence'],
                    'document_title': finding['document_title'], 'location': finding['locator'],
                    'quote': finding['quote'], 'source_url': notice.get('source_url'),
                    'historical_participants': '; '.join(c['name'] + ' (' + c.get('label', 'Zmagovalec') + ')'
                        for c in finding.get('historical_participants', finding.get('historical_winners', [])))}.items()})
    return report


def run(period=PERIOD, max_notices=None, extra_terms='', max_ai_questions=1000, delay=0.5,
        refresh=False, output=None, supplied_profile=None):
    month_dates(period)
    ensure_seed()
    ensure_past_awards()
    profile = supplied_profile or get_profile()
    key, model = gemini_settings()
    fingerprint = profile_fingerprint(profile, extra_terms, model, bool(key and max_ai_questions))
    listed = processed = skipped = ai_used = 0
    for notice_id in grid_rows(period):
        listed += 1
        if max_notices is not None and listed > max_notices:
            listed -= 1
            break
        previous = MonthlyScanItem.objects.filter(period=period, notice_id=notice_id).first()
        if previous and previous.state in ('complete', 'superseded') and previous.fingerprint == fingerprint and not refresh:
            skipped += 1
            continue
        try:
            row = scan_notice(period, notice_id, profile, fingerprint, extra_terms,
                              max(0, max_ai_questions - ai_used), require_ai=bool(key and max_ai_questions))
            ai_used += row.result.get('ai_questions', 0)
        except Exception as exc:
            row, _ = MonthlyScanItem.objects.get_or_create(period=period, notice_id=notice_id)
            row.state = 'error'
            row.result = {'notice_id': notice_id, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
            row.fingerprint = fingerprint
            row.save(update_fields=['state', 'result', 'fingerprint', 'updated_at'])
        processed += 1
        if delay:
            time.sleep(delay)
    path = output or Path(__file__).resolve().parent.parent / 'reports' / f'{period}.json'
    report = write_report(period, path, listed, max_notices is not None)
    return {'listed': listed, 'processed_this_run': processed, 'skipped': skipped,
            'ai_questions': ai_used, 'report': str(path), 'csv': str(Path(path).with_suffix('.csv')),
            'complete': report['complete_count'], 'partial': report['partial_count'],
            'superseded': report['superseded_count'], 'errors': report['error_count'],
            'findings': report['findings_count'],
            'month_complete': report['month_complete']}
