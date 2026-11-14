"""Targeted, repeatable import of offline OCR, without AI or embedding calls."""
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from pypdf.errors import LimitReachedError, PyPdfError

from django.contrib.postgres.search import SearchVector
from django.db import connection, transaction
from django.db.models import Q

from .document_index import chunks
from .deep_relevance import fold
from .models import Document, DocumentChunk, IndexedContent
from .ocr_policy import OCR_IMPORT_VERSION

_PDF_CONTROL_CHARACTERS = dict.fromkeys(code for code in range(32) if code not in (9, 10, 13))


def clean_pages(pages):
    if not isinstance(pages, list) or len(pages) > 10000:
        raise ValueError('Invalid page list')
    result, seen, length = [], set(), 0
    for page in pages:
        number, text = page.get('page'), page.get('text')
        if type(number) is not int or not 1 <= number <= 10000 or number in seen or not isinstance(text, str):
            raise ValueError('Invalid page')
        # PDF font decoders may emit NUL/control glyphs; PostgreSQL JSON/text cannot store NUL.
        text = text.translate(_PDF_CONTROL_CHARACTERS)
        length += len(text)
        if length > 10_000_000:
            raise ValueError('OCR text exceeds import limit')
        seen.add(number)
        locator = page.get('locator') or f'stran {number}'
        if not isinstance(locator, str):
            raise ValueError('Invalid page locator')
        locator = locator.translate(_PDF_CONTROL_CHARACTERS)
        result.append({'page': number, 'text': text, 'locator': locator})
    return sorted(result, key=lambda p: p['page'])


def merge_pages(base, extra):
    """Preserve already readable source text; only fill missing/blank pages."""
    pages = {p['page']: dict(p) for p in base}
    for page in extra:
        old = pages.get(page['page'])
        if old is None or (len(old['text'].strip()) < 20 and len(page['text'].strip()) >= 20):
            pages[page['page']] = dict(page)
    return sorted(pages.values(), key=lambda p: p['page'])


def page_digest(pages):
    return hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source_digest(doc):
    match = re.search(r'/sha256/([0-9a-f]{2})/([0-9a-f]{64})$', doc['path'])
    stored = doc['sha256']
    if stored and not re.fullmatch('[0-9a-f]{64}', stored):
        raise ValueError('Invalid stored digest')
    if match:
        value = match[2]
        if match[1] != value[:2] or (stored and stored != value):
            raise ValueError('Source digest mismatch')
        return value
    if stored:
        return stored
    raise ValueError('No trusted content digest')


def import_results(directory, *, apply=False, before_update=None, progress=None):
    report = {'dry_run': not apply, 'results': 0, 'groups': 0, 'new_contents': 0, 'new_chunks': 0,
              'documents_updated': 0, 'unchanged_documents': 0, 'unusable_results': 0,
              'missing_text_results': 0, 'errors': []}
    records = {}
    for file in sorted(Path(directory).glob('*.json')):
        raw = json.loads(file.read_text())
        records[raw['id']] = raw
    report['results'] = len(records)
    metadata = {d['id']: d for d in Document.objects.values('id', 'path', 'sha256', 'extraction')}
    groups = defaultdict(lambda: {'pages': [], 'sources': set(), 'native': False})
    for key, raw in records.items():
        try:
            if raw.get('status') not in ('ocr', 'text_present', 'duplicate'):
                report['unusable_results'] += 1
                continue
            doc = metadata.get(key)
            if doc is None or doc['path'] != raw.get('source'):
                raise ValueError('Document missing or source changed')
            if doc['extraction'].get('mode') == 'archive':
                continue
            digest = source_digest(doc)
            source, seen = raw, set()
            while source.get('status') == 'duplicate':
                if source['id'] in seen:
                    raise ValueError('Duplicate cycle')
                seen.add(source['id'])
                source = records.get(source.get('duplicate_of'), {})
            pages = []
            if source.get('pages'):
                if source.get('source') != raw['source']:
                    raise ValueError('Duplicate source mismatch')
                pages = clean_pages(source['pages'])
            group = groups[digest]
            group['sources'].add(doc['path'])
            group['native'] = group['native'] or source.get('status') == 'text_present'
            group['pages'] = merge_pages(group['pages'], pages)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            report['errors'].append({'id': key, 'error': str(exc)})
    report['groups'] = len(groups)
    for number, (digest, group) in enumerate(sorted(groups.items()), 1):
        report['groups_processed'] = number
        with transaction.atomic():
            query = Document.objects.filter(Q(sha256=digest) | Q(path__in=group['sources']))
            if apply:
                query = query.select_for_update()
            docs = [d for d in query if d.extraction.get('mode') != 'archive'
                    and (not d.sha256 or d.sha256 == digest)]
            contents = list(IndexedContent.objects.filter(sha256=digest, pk__in={d.indexed_content_id for d in docs
                                                                                if d.indexed_content_id}))
            # Start from the best existing native/indexed copy, so a partial OCR cannot degrade it.
            contents.sort(key=lambda c: (sum(len(p.get('text', '').strip()) >= 20 for p in c.pages),
                                         sum(len(p.get('text', '')) for p in c.pages)), reverse=True)
            pages = []
            for content in contents:
                pages = merge_pages(pages, clean_pages(content.pages))
            for doc in docs:
                pages = merge_pages(pages, clean_pages(doc.pages))
            pages = merge_pages(pages, group['pages'])
            if group['native'] and docs and sum(len(p['text'].strip()) for p in pages) < 20:
                # A text_present sidecar has no page payload. Read only its existing native PDF text.
                from .documents import extract_pages
                from .pipeline_storage import local_file
                try:
                    with local_file(docs[0].path) as path:
                        native = extract_pages(path, max_bytes=50 * 1024**2, max_pages=500)
                    pages = merge_pages(pages, clean_pages(native))
                except (OSError, ValueError, PyPdfError, LimitReachedError, BotoCoreError, ClientError) as exc:
                    report['errors'].append({'id': docs[0].pk, 'error': type(exc).__name__})
            if sum(len(p['text'].strip()) for p in pages) < 20:
                report['missing_text_results'] += 1
                continue
            signature = page_digest(pages)
            content = next((c for c in contents if c.format == 'pdf'
                            and page_digest(clean_pages(c.pages)) == signature), None)
            if content is None:
                identity = hashlib.sha256(f'{digest}:{OCR_IMPORT_VERSION}:{signature}'.encode()).hexdigest()
                content = IndexedContent.objects.filter(pk=identity).first()
                if content is None:
                    passages = list(chunks(pages))
                    report['new_contents'] += 1
                    report['new_chunks'] += len(passages)
                    if apply:
                        content, created = IndexedContent.objects.get_or_create(pk=identity, defaults={
                            'sha256': digest, 'extractor_version': OCR_IMPORT_VERSION,
                            'pages': pages, 'format': 'pdf'})
                        if created:
                            DocumentChunk.objects.bulk_create([DocumentChunk(content=content, ordinal=i,
                                page=page, locator=locator, text=text, normalized_text=fold(text))
                                for i, (page, locator, text) in enumerate(passages)], batch_size=100)
                            if connection.vendor == 'postgresql':
                                content.chunks.update(search_vector=SearchVector('normalized_text', config='simple'))
                    else:
                        content = IndexedContent(id=identity, sha256=digest, extractor_version=OCR_IMPORT_VERSION,
                                                 pages=pages, format='pdf')
            blank = sum(len(p['text'].strip()) < 20 for p in content.pages)
            for doc in docs:
                if (doc.indexed_content_id == content.pk and doc.pages == content.pages
                        and doc.status == 'processed' and not doc.error):
                    report['unchanged_documents'] += 1
                    continue
                report['documents_updated'] += 1
                if apply:
                    if before_update:
                        before_update({'id': doc.pk, 'indexed_content_id': doc.indexed_content_id,
                            'sha256': doc.sha256, 'pages': doc.pages, 'status': doc.status,
                            'error': doc.error, 'extraction': doc.extraction})
                    # Reset cached document analysis; importing does not enqueue its replacement.
                    extraction = {'mode': 'unprocessed', 'format': 'pdf',
                                  'index_version': content.extractor_version,
                                  'ocr_import': {'version': OCR_IMPORT_VERSION,
                                                 'remaining_blank_pages': blank}}
                    Document.objects.filter(pk=doc.pk).update(indexed_content=content, sha256=digest,
                        pages=content.pages, status='processed', error='', extraction=extraction)
        if progress:
            progress(report)
    return report
