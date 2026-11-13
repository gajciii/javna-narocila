"""Semantic vectors for document passages, tenders and past awards.

Vectors are filled in the background by the pipeline worker when it has no jobs, so
indexing never waits on (or fails because of) the embedding provider. Passages are shared
by content hash, so identical files are embedded once. Tenders and awards keep a digest of
the embedded text and are re-embedded only when that text changes.
"""
import hashlib
import logging
import os

from django.db import connection, transaction

from .models import DocumentChunk, PastAward, Tender

log = logging.getLogger(__name__)

MODEL = 'openai/text-embedding-3-large'
DIMENSIONS = 1024
BATCH = 96  # Passages are at most ~1800 characters, far below the per-request token limit.
MAX_TEXT = 8000


def enabled():
    return connection.vendor == 'postgresql' and bool(os.environ.get('OPENROUTER_API_KEY'))


def embed(texts, timeout=60):
    from openai import OpenAI
    from .ai import OPENROUTER_BASE_URL
    client = OpenAI(api_key=os.environ['OPENROUTER_API_KEY'], base_url=OPENROUTER_BASE_URL, timeout=timeout,
                    max_retries=2, default_headers={'X-Title': 'RazpIzi'})
    response = client.embeddings.create(model=MODEL, input=[t[:MAX_TEXT] for t in texts], dimensions=DIMENSIONS,
                                        extra_body={'provider': {'data_collection': 'deny'}})
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
        raise ValueError('Ponudnik je vrnil nepričakovano število ali dolžino vektorjev.')
    return vectors


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


def store(model, rows, texts, digests=None):
    vectors = embed(texts)
    for index, (row, vector) in enumerate(zip(rows, vectors)):
        fields = {'embedding': vector}
        if digests is not None:
            fields['embedding_digest'] = digests[index]
        model.objects.filter(pk=row).update(**fields)
    return len(rows)


def embed_chunks(limit=BATCH):
    with transaction.atomic():
        # skip_locked lets several workers fill vectors without embedding the same passage twice.
        rows = list(DocumentChunk.objects.select_for_update(skip_locked=True).filter(embedding__isnull=True)
                    .order_by('pk').values_list('pk', 'text')[:limit])
        return store(DocumentChunk, [r[0] for r in rows], [r[1] for r in rows]) if rows else 0


def embed_awards(limit=BATCH):
    with transaction.atomic():
        rows = list(PastAward.objects.select_for_update(skip_locked=True).filter(embedding__isnull=True)
                    .order_by('-published_on', 'pk').values_list('pk', 'data')[:limit])
        texts = [award_text(data) or 'Javno naročilo' for _, data in rows]
        return store(PastAward, [r[0] for r in rows], texts, [digest(t) for t in texts]) if rows else 0


def stale_tenders(limit=BATCH):
    """Tenders change in place, so compare the digest of their current text (a few thousand rows)."""
    stale = []
    for pk, data, current in Tender.objects.values_list('pk', 'data', 'embedding_digest').iterator():
        text = tender_text(data)
        if text and digest(text) != current:
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
    return {'tenders': len(stale_tenders(limit=10**6)),
            'chunks': DocumentChunk.objects.filter(embedding__isnull=True).count(),
            'awards': PastAward.objects.filter(embedding__isnull=True).count()}
