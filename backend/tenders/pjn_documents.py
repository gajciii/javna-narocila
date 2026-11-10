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


def download_documents(tender):
    meta = dict(tender.data.get('source_metadata', {}))
    url = meta.get('attachment_url')
    if not url or meta.get('access_restricted') or not official_url(url, attachment=True):
        return {'downloaded': 0, 'warning': 'Dokumentacija nima javne povezave za prenos s portala. Odprite izvorno objavo.'}
    try:
        payload, headers = fetch(url, max_bytes=MAX_FILE)
        message = Message()
        message['content-disposition'] = headers.get('Content-Disposition', '')
        title = message.get_filename() or ('Dokumentacija.pdf' if payload.startswith(b'%PDF-') else 'Dokumentacija.zip' if payload.startswith(b'PK') else 'Dokumentacija')
        if zipfile.is_zipfile(io.BytesIO(payload)):
            container = store_file(tender, title, payload, container=True)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = [m for m in archive.infolist() if not m.is_dir()]
                if len(members) > 30 or sum(m.file_size for m in members) > MAX_EXPANDED or any(m.file_size > MAX_FILE or m.flag_bits & 1 or stat.S_ISLNK(m.external_attr >> 16) for m in members):
                    container.status = 'unprocessed'
                    container.error = 'ZIP presega omejitve ali vsebuje zaščitene datoteke. Preglejte izvorni arhiv.'
                    container.save(update_fields=['status', 'error'])
                    return {'downloaded': 1, 'warning': container.error}
                for member in members:
                    # Never extract archive paths onto the filesystem.
                    store_file(tender, member.filename, archive.read(member))
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
