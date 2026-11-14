"""Explicit, paid embedding pass restricted to the imported OCR content version."""
from django.db import transaction
from django.db.models import Exists, OuterRef

from . import embeddings
from .models import Document, DocumentChunk
from .ocr_policy import OCR_IMPORT_VERSION


def ocr_chunks(maximum_pk=None):
    linked = Document.objects.filter(indexed_content_id=OuterRef('content_id'))
    rows = DocumentChunk.objects.filter(content__extractor_version=OCR_IMPORT_VERSION).filter(Exists(linked))
    return rows.filter(pk__lte=maximum_pk) if maximum_pk is not None else rows


def embed_ocr_batch(limit=embeddings.BATCH, maximum_pk=None):
    """Skip existing vectors; share the normal row locks without enabling automatic OCR embedding."""
    with transaction.atomic():
        rows = list(ocr_chunks(maximum_pk).select_for_update(skip_locked=True, of=('self',))
                    .filter(embedding__isnull=True).exclude(pk__in=embeddings._rejected[DocumentChunk])
                    .order_by('pk').values_list('pk', 'text')[:limit])
        if not rows:
            return 0
        return embeddings.store(DocumentChunk, [pk for pk, _ in rows], [text for _, text in rows])
