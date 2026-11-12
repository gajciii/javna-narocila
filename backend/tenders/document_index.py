"""Extract once, index all passages, retrieve candidates for any company."""
import hashlib
import json
import re

from django.db import connection, transaction
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

from .deep_extract import extract_document
from .deep_relevance import fold, prefixes
from .models import DocumentChunk, IndexedContent
from .pipeline_storage import local_file

EXTRACTOR_VERSION = 'shared-v1'
CHUNK_SIZE = 1800


def chunks(pages):
    """Keep exact source substrings, page locations, and overlapping context."""
    for page in pages:
        text = page.get('text', '')
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_SIZE)
            if end < len(text):
                boundary = text.rfind('\n', start + CHUNK_SIZE // 2, end)
                if boundary > start:
                    end = boundary
            quote = text[start:end].strip()
            if len(quote) >= 20:
                yield page['page'], page.get('locator') or f"stran {page['page']}", quote
            if end >= len(text):
                break
            start = max(start + 1, end - 180)


def index_document(document, pages=None):
    """``pages`` lets generated text (e.g. portal Q&A) keep its own locators instead of file parsing."""
    if document.extraction.get('mode') == 'archive':
        return None
    digest = document.sha256
    if not digest:
        with local_file(document.path) as path:
            h = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    h.update(block)
            digest = h.hexdigest()
    identity = hashlib.sha256(f'{digest}:{EXTRACTOR_VERSION}'.encode()).hexdigest()
    content = IndexedContent.objects.filter(pk=identity).first()
    if content is None:
        if pages is not None:
            kind = 'txt'
        else:
            with local_file(document.path) as path:
                pages, kind = extract_document(path, document.title)
        if sum(len(p.get('text', '').strip()) for p in pages) < 20:
            raise ValueError('Dokument nima berljivega besedila; potreben je OCR ali ročni pregled.')
        with transaction.atomic():
            content, created = IndexedContent.objects.get_or_create(pk=identity,
                defaults={'sha256': digest, 'extractor_version': EXTRACTOR_VERSION, 'pages': pages, 'format': kind})
            if created:
                DocumentChunk.objects.bulk_create([DocumentChunk(content=content, ordinal=i, page=page,
                    locator=locator, text=text, normalized_text=fold(text))
                    for i, (page, locator, text) in enumerate(chunks(pages))], batch_size=100)
                if connection.vendor == 'postgresql':
                    content.chunks.update(search_vector=SearchVector('normalized_text', config='simple'))
    document.indexed_content = content
    document.sha256 = digest
    document.pages = content.pages
    document.status = 'processed'
    document.error = ''
    document.extraction = {'mode': 'unprocessed', **document.extraction, 'format': content.format,
                           'index_version': EXTRACTOR_VERSION}
    document.save(update_fields=['indexed_content', 'sha256', 'pages', 'status', 'error', 'extraction'])
    return content


def index_key(documents):
    return hashlib.sha256(json.dumps(sorted((d.pk, d.version, d.status,
        d.indexed_content_id, d.error) for d in documents)).encode()).hexdigest()


def search_passages(documents, profile, extra_terms='', limit=40, terms=None):
    terms = sorted(terms if terms is not None else prefixes(profile, extra_terms))[:150]
    if not terms:
        return [], 0
    by_content = {}
    for document in documents:
        if document.indexed_content_id:
            by_content.setdefault(document.indexed_content_id, document)
    candidates = DocumentChunk.objects.filter(content_id__in=by_content)
    if connection.vendor == 'postgresql':
        # Only locally tokenized alphanumeric terms enter tsquery syntax; SQL stays parameterized.
        terms = [t for t in terms if re.fullmatch(r'\w+', t)]
        if not terms:
            return [], 0
        query = SearchQuery(' | '.join(f'{term}:*' for term in terms), config='simple', search_type='raw')
        candidates = candidates.filter(search_vector=query).annotate(
            rank=SearchRank('search_vector', query)).order_by('-rank', 'pk')
        total = candidates.count()
        selected = list(candidates[:limit])
    else:
        # SQLite is supported for offline tests and the original local demo only.
        selected = [c for c in candidates.order_by('pk')
                    if any(word.startswith(tuple(terms)) for word in re.findall(r'\w+', c.normalized_text))]
        total, selected = len(selected), selected[:limit]
    found = []
    for chunk in selected:
        doc = by_content[chunk.content_id]
        found.append({'document_id': doc.pk, 'document_title': doc.title,
            'page': chunk.page if doc.extraction.get('format') == 'pdf' else None,
            'locator': chunk.locator, 'quote': chunk.text, 'matched_term': '',
            'document_url': f'/api/documents/{doc.pk}'})
    return found, max(0, total - limit)
