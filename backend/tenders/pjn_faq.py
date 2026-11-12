"""Questions, answers and clarifications published on an e-Naročanje dossier.

The portal publishes all buyer answers on the first notice of the dossier, so we read the
FAQ list of that notice (and of the current notice, in case a later one carries its own).
Collected items are stored as ``TenderQuestion`` rows and as one plain-text document that
goes through the shared index, so searches, condition extraction and the assistant see them.
"""
import hashlib
import html
import json
import logging
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from .models import Document, Tender, TenderQuestion
from .pjn_transport import fetch_json, safe_error

log = logging.getLogger(__name__)

FAQ_TITLE = 'Vprašanja in odgovori (e-Naročanje).txt'
REFRESH_AFTER = timedelta(minutes=15)
KINDS = {3: 'clarification'}
TAG = re.compile(r'<[^>]+>')
SPLIT = re.compile(r'^\s*ODGOVOR\s*:?\s*$', re.M)
QUESTION_HEAD = re.compile(r'^\s*VPRAŠANJE\s*:?\s*\n', re.I)


def plain(text):
    text = re.sub(r'<br\s*/?>|</p>', '\n', text or '', flags=re.I)
    return re.sub(r'\n{3,}', '\n\n', html.unescape(TAG.sub('', text))).strip()


def parse_item(raw):
    text = plain(raw.get('tekst'))
    kind = KINDS.get(raw.get('idSifObrazecFaqTip'), 'question')
    question, answer = text, ''
    if kind == 'question':
        parts = SPLIT.split(text, maxsplit=1)
        question = QUESTION_HEAD.sub('', parts[0]).strip()
        answer = parts[1].strip() if len(parts) > 1 else ''
    return {'id': raw.get('id'), 'notice_id': str(raw.get('idObrazec') or ''), 'kind': kind,
            'question': question, 'answer': answer, 'published_at': raw.get('datumVnosa') or raw.get('mdTs')}


def supported(tender):
    meta = tender.data.get('source_metadata') or {}
    return tender.data.get('source_type') == 'real' and isinstance(meta.get('dossier_id'), int)


def notice_ids(meta):
    forms = fetch_json(f"obrazec/objava/dosjeObrazecGetList?idDosje={int(meta['dossier_id'])}")
    forms = [f for f in forms if isinstance(f, dict) and isinstance(f.get('idObrazec'), int)] if isinstance(forms, list) else []
    forms.sort(key=lambda f: (f.get('objavaDejanskaDatum') or '', f['idObrazec']))
    ids = [forms[0]['idObrazec']] if forms else []
    if str(meta.get('notice_id') or '').isdigit() and int(meta['notice_id']) not in ids:
        ids.append(int(meta['notice_id']))
    return ids


def fetch_items(tender):
    seen, items = set(), []
    for notice_id in notice_ids(tender.data['source_metadata']):
        rows = fetch_json(f'obrazecFaq/obrazecFaqGetList?idObrazec={notice_id}')
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get('id'), int) and row['id'] not in seen:
                seen.add(row['id'])
                items.append(parse_item(row))
    return sorted(items, key=lambda item: (item['published_at'] or '', item['id']))


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def items_digest(items):
    if not items:
        return None
    rows = [[i['id'], i['kind'], i['question'], i['answer']] for i in items]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:32]


def label(item, number):
    when = parse_time(item['published_at'])
    title = 'Pojasnilo naročnika' if item['kind'] == 'clarification' else 'Vprašanje'
    return f"{title} {number}" + (f", objavljeno {when.astimezone(timezone.get_current_timezone()):%d. %m. %Y}" if when else '')


def pages_for(tender, items):
    """One page per item keeps citations pointing at a single question and its answer."""
    pages = []
    for number, item in enumerate(items, 1):
        text = item['question'] if item['kind'] == 'clarification' else (
            f"VPRAŠANJE PONUDNIKA:\n{item['question']}\n\nODGOVOR NAROČNIKA:\n{item['answer'] or 'Naročnik še ni odgovoril.'}")
        pages.append({'page': number, 'locator': label(item, number), 'text': f"{label(item, number)}\n{text}"})
    return pages


def document_text(tender, pages):
    head = (f"VPRAŠANJA, ODGOVORI IN POJASNILA\n{tender.data.get('title', '')}\n"
            f"Vir: e-Naročanje, {tender.data.get('source_url', '')}\n")
    return head + ''.join(f"\n\n=== {p['text']}" for p in pages) + '\n'


def store_document(tender, items):
    """Keep one FAQ document per tender; identical text reuses the shared index entry."""
    from .document_index import index_document
    from .pipeline_storage import store
    doc_id = f'faq-{tender.pk}'[:100]
    if not items:
        Document.objects.filter(pk=doc_id).delete()
        return None
    pages = pages_for(tender, items)
    payload = document_text(tender, pages).encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    document = Document.objects.filter(pk=doc_id).first()
    version = tender.data.get('version', 1)
    if document and document.sha256 == digest and document.indexed_content_id:
        if document.version != version:
            Document.objects.filter(pk=doc_id).update(version=version)
        return document
    with tempfile.TemporaryDirectory(prefix='razpizi-faq-') as directory:
        path = Path(directory) / 'faq.txt'
        path.write_bytes(payload)
        reference = store(path, digest)
    document, _ = Document.objects.update_or_create(pk=doc_id, defaults={
        'tender': tender, 'title': FAQ_TITLE, 'version': version, 'path': reference, 'sha256': digest,
        'size_bytes': len(payload), 'status': 'unprocessed', 'error': '', 'pages': [], 'indexed_content': None,
        'extraction': {'mode': 'unprocessed', 'source': 'pjn-faq'}})
    index_document(document, pages=pages)
    return document


def sync_faq(tender):
    """Fetch, store and index the dossier's questions. Raises when the portal is unavailable."""
    if not supported(tender):
        return {'count': 0, 'changed': False}
    items = fetch_items(tender)
    digest = items_digest(items)
    with transaction.atomic():
        tender = Tender.objects.select_for_update().get(pk=tender.pk)
        meta = tender.data.get('source_metadata') or {}
        changed = meta.get('faq_digest') != digest
        ids = [item['id'] for item in items]
        TenderQuestion.objects.filter(tender=tender).exclude(source_id__in=ids).delete()
        for item in items:
            TenderQuestion.objects.update_or_create(tender=tender, source_id=item['id'], defaults={
                'notice_id': item['notice_id'], 'kind': item['kind'], 'question': item['question'],
                'answer': item['answer'], 'published_at': parse_time(item['published_at'])})
        meta = {**meta, 'faq_synced_at': timezone.now().isoformat(), 'faq_count': len(items)}
        if digest:
            meta['faq_digest'] = digest
        else:
            meta.pop('faq_digest', None)  # Tenders without questions keep their original index identity.
        tender.data = {**tender.data, 'source_metadata': meta}
        tender.save(update_fields=['data', 'updated_at'])
    if changed or (items and not Document.objects.filter(pk=f'faq-{tender.pk}'[:100], indexed_content__isnull=False).exists()):
        store_document(tender, items)
    return {'count': len(items), 'changed': changed, 'tender': tender}


def try_sync(tender, requeue=False):
    """Best-effort sync for collectors; requeues indexing so conditions see new answers."""
    try:
        result = sync_faq(tender)
    except Exception as exc:
        log.warning('FAQ sync failed for %s: %s', tender.pk, safe_error(exc))
        return {'count': 0, 'changed': False, 'error': safe_error(exc)}
    if requeue and result['changed']:
        from django.conf import settings
        if settings.PIPELINE_REMOTE:
            from .pipeline_jobs import enqueue_index
            enqueue_index(result['tender'])
    return result


def stale(tender):
    synced = parse_time((tender.data.get('source_metadata') or {}).get('faq_synced_at'))
    return synced is None or timezone.now() - synced > REFRESH_AFTER


def serialize(question):
    return {'id': question.source_id, 'kind': question.kind, 'question': question.question,
            'answer': question.answer, 'published_at': question.published_at.isoformat() if question.published_at else None}


def tender_faq(tender):
    if not supported(tender):
        return {'available': False, 'items': [], 'message': 'Vprašanja in odgovori so na voljo samo za objave iz e-Naročanja.'}
    error = ''
    # Answers keep arriving until the deadline; refresh open tenders when the stored copy is old.
    from .matching import effective_status
    never = not (tender.data.get('source_metadata') or {}).get('faq_synced_at')
    if never or (stale(tender) and effective_status(tender.data) in ('open', 'unconfirmed')):
        result = try_sync(tender, requeue=True)
        error = result.get('error', '')
        tender.refresh_from_db()
    meta = tender.data.get('source_metadata') or {}
    rows = [serialize(q) for q in tender.questions.order_by('-published_at', '-source_id')]
    payload = {'available': True, 'items': rows, 'source_url': tender.data.get('source_url'),
               'synced_at': meta.get('faq_synced_at'), 'document_id': f'faq-{tender.pk}'[:100] if rows else None}
    if error and meta.get('faq_synced_at'):
        payload['warning'] = 'Osvežitev s portala ni uspela; prikazana je zadnja shranjena različica.'
    elif error:
        payload['error'] = error
    return payload
