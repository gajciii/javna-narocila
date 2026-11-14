"""Semantic vectors for document passages, tenders and past awards.

Vectors are filled in the background by the pipeline worker when it has no jobs, so
indexing never waits on (or fails because of) the embedding provider. Passages are shared
by content hash, so identical files are embedded once. Tenders and awards keep a digest of
the embedded text and are re-embedded only when that text changes.
"""
import functools
import hashlib
import logging
import os

from django.db import connection, transaction

from .models import DocumentChunk, PastAward, Tender

log = logging.getLogger(__name__)

MODEL = 'openai/text-embedding-3-large'
DIMENSIONS = 1024
BATCH = 96  # Passages are at most ~1800 characters, far below the per-request token limit.
EF_SEARCH = 400  # pgvector's default of 40 missed clear matches; 400 matched exact search in tests.
MAX_TEXT = 6000  # Characters; stays below the model's 8191-token input limit.

# Rows the provider permanently rejects are skipped until the worker restarts, so a single
# bad row cannot block every batch behind it. Transient errors simply retry the batch.
_rejected = {DocumentChunk: set(), PastAward: set(), Tender: set()}


def enabled():
    return connection.vendor == 'postgresql' and bool(os.environ.get('OPENROUTER_API_KEY'))


def embed(texts, timeout=60, retries=2):
    from openai import OpenAI
    from .ai import OPENROUTER_BASE_URL
    client = OpenAI(api_key=os.environ['OPENROUTER_API_KEY'], base_url=OPENROUTER_BASE_URL, timeout=timeout,
                    max_retries=retries, default_headers={'X-Title': 'RazpIzi'})
    response = client.embeddings.create(model=MODEL, input=[t[:MAX_TEXT] for t in texts], dimensions=DIMENSIONS,
                                        extra_body={'provider': {'data_collection': 'deny'}})
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
        raise ValueError('Ponudnik je vrnil nepričakovano število ali dolžino vektorjev.')
    return vectors


@functools.lru_cache(maxsize=512)
def query_vector(text, timeout=60, retries=2):
    """Search queries repeat (same tender, same keywords), so each process keeps recent vectors."""
    return tuple(embed([text], timeout=timeout, retries=retries)[0])


def similarities(model, text, ids, timeout=6):
    """Cosine similarity of ``text`` to each listed row that has a vector. Exact, not approximate:
    a search compares against every listed row, so the best match per query is always known."""
    from pgvector.django import CosineDistance
    vector = list(query_vector(text, timeout, 1))
    rows = (model.objects.filter(pk__in=list(ids), embedding__isnull=False)
            .annotate(distance=CosineDistance('embedding', vector)).values_list('pk', 'distance'))
    return {pk: 1 - distance for pk, distance in rows}


def nearest(queryset, text, limit):
    """Rows ordered by cosine distance to ``text``; each row gets a ``distance`` attribute."""
    from pgvector.django import CosineDistance
    vector = list(query_vector(text))
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET LOCAL hnsw.ef_search = %s', [EF_SEARCH])
        return list(queryset.annotate(distance=CosineDistance('embedding', vector)).order_by('distance')[:limit])


def digest(text):
    return hashlib.sha256(f'{MODEL}:{DIMENSIONS}:{text}'.encode()).hexdigest()[:32]


def join(*parts):
    return '\n'.join(str(p).strip() for p in parts if p and str(p).strip())


def tender_text(data):
    return join(data.get('title'), data.get('buyer') and f"Naročnik: {data['buyer']}", data.get('summary'),
                ', '.join(data.get('topics') or []), ', '.join(data.get('technologies') or []),
                ', '.join(data.get('cpv') or []))


def award_text(data):
    title = join(data.get('title'), data.get('lot_title'))
    return join(title, data.get('buyer') and f"Naročnik: {data['buyer']}", data.get('description'),
                ', '.join(data.get('cpv') or []))


def rejected(exc):
    from openai import BadRequestError
    return isinstance(exc, BadRequestError)


def save(model, row, vector, digest_value):
    fields = {'embedding': vector}
    if digest_value is not None:
        fields['embedding_digest'] = digest_value
    model.objects.filter(pk=row).update(**fields)


def store(model, rows, texts, digests=None):
    digests = digests or [None] * len(rows)
    try:
        vectors = embed(texts)
    except Exception as exc:
        if not rejected(exc):
            raise
        # Find the rejected rows one by one; the others are stored normally.
        for row, text, digest_value in zip(rows, texts, digests):
            try:
                save(model, row, embed([text])[0], digest_value)
            except Exception as single:
                if not rejected(single):
                    raise
                _rejected[model].add(row)
                log.warning('Embedding rejected for %s %s', model.__name__, row)
        return len(rows)
    for row, vector, digest_value in zip(rows, vectors, digests):
        save(model, row, vector, digest_value)
    return len(rows)


def embed_chunks(limit=BATCH):
    from .ocr_policy import OCR_IMPORT_PREFIX
    with transaction.atomic():
        # skip_locked lets several workers fill vectors without embedding the same passage twice.
        rows = list(DocumentChunk.objects.select_for_update(skip_locked=True, of=('self',)).filter(embedding__isnull=True)
                    .exclude(content__extractor_version__startswith=OCR_IMPORT_PREFIX)
                    .exclude(pk__in=_rejected[DocumentChunk]).order_by('pk').values_list('pk', 'text')[:limit])
        return store(DocumentChunk, [r[0] for r in rows], [r[1] for r in rows]) if rows else 0


def embed_awards(limit=BATCH):
    with transaction.atomic():
        rows = list(PastAward.objects.select_for_update(skip_locked=True).filter(embedding__isnull=True)
                    .exclude(pk__in=_rejected[PastAward]).order_by('-published_on', 'pk').values_list('pk', 'data')[:limit])
        texts = [award_text(data) or 'Javno naročilo' for _, data in rows]
        return store(PastAward, [r[0] for r in rows], texts, [digest(t) for t in texts]) if rows else 0


def stale_tenders(limit=BATCH):
    """Tenders change in place, so compare the digest of their current text (a few thousand rows)."""
    stale = []
    for pk, data, current in Tender.objects.values_list('pk', 'data', 'embedding_digest').iterator():
        text = tender_text(data)
        if text and digest(text) != current and pk not in _rejected[Tender]:
            stale.append((pk, text))
            if len(stale) >= limit:
                break
    return stale


def embed_tenders(limit=BATCH):
    rows = stale_tenders(limit)
    if not rows:
        return 0
    texts = [text for _, text in rows]
    return store(Tender, [pk for pk, _ in rows], texts, [digest(t) for t in texts])


def award_invalidation(old, data):
    """Fields that reset an award vector when an updated notice changes its text."""
    if old is None or old.embedding_digest == digest(award_text(data) or 'Javno naročilo'):
        return {}
    return {'embedding': None, 'embedding_digest': ''}


def embed_pending(limit=BATCH):
    """Fill one batch, most useful first: tenders, then document passages, then past awards."""
    if not enabled():
        return 0
    for step in (embed_tenders, embed_chunks, embed_awards):
        done = step(limit)
        if done:
            return done
    return 0


def pending_counts():
    from .ocr_policy import OCR_IMPORT_PREFIX
    return {'tenders': len(stale_tenders(limit=10**6)),
            'chunks': DocumentChunk.objects.filter(embedding__isnull=True).exclude(content__extractor_version__startswith=OCR_IMPORT_PREFIX).count(),
            'awards': PastAward.objects.filter(embedding__isnull=True).count()}
