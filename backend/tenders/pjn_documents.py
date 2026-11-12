import hashlib
import io
import stat
import zipfile
from email.message import Message
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .documents import extract_pages
from .models import Document
from .pjn_transport import fetch, official_url, safe_error

MAX_FILE = 10 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024
OFFICE_SUFFIXES = ('.docx', '.xlsx', '.pptx', '.odt', '.ods')


def store_file(tender, title, payload, container=False):
    title = Path(title.replace('\\', '/')).name[:250] or 'Dokumentacija'
    digest = hashlib.sha256(payload).hexdigest()
    identity = hashlib.sha256((tender.id + str(tender.data['version']) + title + digest).encode()).hexdigest()[:24]
    previous = Document.objects.filter(pk='pjn-doc-' + identity).first()
    if previous:
        return previous
    pdf = payload.startswith(b'%PDF-')
    root = settings.MEDIA_ROOT / 'pjn'
    root.mkdir(parents=True, exist_ok=True)
    path = root / (identity + ('.pdf' if pdf else '.zip' if container else '.bin'))
    path.write_bytes(payload)
    pages, error = [], ''
    if pdf:
        try:
            pages = extract_pages(path)
            if sum(len(p['text'].strip()) for p in pages) < 50:
                error = 'PDF nima berljive besedilne plasti; potreben je OCR.'
        except Exception:
            error = 'PDF-ja ni bilo mogoče obdelati v omejitvah prototipa.'
    elif not container:
        error = 'Format priloge še ni podprt. Dokument je shranjen za ročni pregled.'
    return Document.objects.create(id='pjn-doc-' + identity, tender=tender, version=tender.data['version'],
        title=title, path=str(path), pages=pages, sha256=digest, error=error,
        status='unprocessed' if error else 'processed',
        extraction={'mode': 'archive' if container else 'unprocessed', 'requirements': [], 'criteria': [], 'summary': ''})


def download_documents(tender, max_file=MAX_FILE, max_expanded=MAX_EXPANDED, max_members=30):
    meta = dict(tender.data.get('source_metadata', {}))
    url = meta.get('attachment_url')
    if not url or meta.get('access_restricted') or not official_url(url, attachment=True):
        return {'downloaded': 0, 'warning': 'Dokumentacija nima javne povezave za prenos s portala. Odprite izvorno objavo.'}
    try:
        payload, headers = fetch(url, max_bytes=max_file)
        message = Message()
        message['content-disposition'] = headers.get('Content-Disposition', '')
        title = message.get_filename() or ('Dokumentacija.pdf' if payload.startswith(b'%PDF-') else 'Dokumentacija.zip' if payload.startswith(b'PK') else 'Dokumentacija')
        if zipfile.is_zipfile(io.BytesIO(payload)) and not title.lower().endswith(OFFICE_SUFFIXES):
            container = store_file(tender, title, payload, container=True)
            budget = {'members': 0, 'expanded': 0}

            def unpack(data, depth):
                if depth > 2:
                    raise ValueError('Gnezdeni ZIP presega dovoljeno globino.')
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = [m for m in archive.infolist() if not m.is_dir()]
                    budget['members'] += len(members)
                    budget['expanded'] += sum(m.file_size for m in members)
                    if (budget['members'] > max_members or budget['expanded'] > max_expanded or
                        any(m.file_size > max_file or m.flag_bits & 1 or stat.S_ISLNK(m.external_attr >> 16) for m in members)):
                        raise ValueError('ZIP presega omejitve ali vsebuje zaščitene datoteke.')
                    for member in members:
                        # Archive paths are never used as local filesystem paths.
                        content = archive.read(member)
                        stored = store_file(tender, member.filename, content)
                        if zipfile.is_zipfile(io.BytesIO(content)) and not member.filename.lower().endswith(OFFICE_SUFFIXES):
                            stored.extraction['mode'] = 'archive'
                            stored.status = 'processed'
                            stored.error = ''
                            stored.save(update_fields=['extraction', 'status', 'error'])
                            unpack(content, depth + 1)
            try:
                unpack(payload, 0)
            except (ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                container.status = 'unprocessed'
                container.error = str(exc)[:300]
                container.save(update_fields=['status', 'error'])
                return {'downloaded': tender.document_records.filter(version=tender.data['version']).count(), 'warning': container.error}
        else:
            store_file(tender, title, payload)
        documents = list(tender.document_records.filter(version=tender.data['version']))
        meta['attachments_processed'] = bool(documents) and all(d.status == 'processed' for d in documents)
        meta['documents_downloaded_at'] = timezone.now().isoformat()
        tender.data = {**tender.data, 'source_metadata': meta}
        tender.save(update_fields=['data'])
        return {'downloaded': len(documents), 'warning': 'Pogoji iz dokumentacije še niso potrjeni. Za AI analizo nastavite ključ ali dokumente preglejte ročno.'}
    except Exception as exc:
        return {'downloaded': 0, 'warning': safe_error(exc)}
