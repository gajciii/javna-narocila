"""Stream multi-GB PJN archives to disk and unpack one member at a time."""
import hashlib
import shutil
import stat
import tempfile
import zipfile
from email.message import Message
from pathlib import Path
from urllib.parse import urljoin

import requests
from django.conf import settings

from .models import Document
from .pipeline_storage import store
from .pjn_transport import official_url, HEADERS

OFFICE = ('.docx', '.xlsx', '.pptx', '.odt', '.ods')


def copy_stream(source, path, maximum):
    digest, size = hashlib.sha256(), 0
    with path.open('wb') as target:
        for block in source:
            size += len(block)
            if size > maximum:
                raise ValueError('Datoteka presega nastavljeno omejitev prenosa.')
            if shutil.disk_usage(path.parent).free < len(block) + 256 * 1024**2:
                raise ValueError('Na delavcu ni dovolj prostora za nadaljevanje.')
            target.write(block)
            digest.update(block)
    return digest.hexdigest()


def fetch_file(url, path):
    for _ in range(3):
        if not official_url(url, attachment=True):
            raise ValueError('Priloga ni na uradnem portalu.')
        with requests.get(url, headers=HEADERS, stream=True, allow_redirects=False, timeout=(10, 90)) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            if response.status_code != 200:
                raise ValueError(f'Prenos priloge: HTTP {response.status_code}.')
            digest = copy_stream(response.iter_content(1024 * 1024), path, settings.PIPELINE_MAX_DOWNLOAD)
            message = Message()
            message['content-disposition'] = response.headers.get('Content-Disposition', '')
            return digest, message.get_filename() or 'Dokumentacija'
    raise ValueError('Preveč preusmeritev priloge.')


def register(tender, path, title, digest, archive=False):
    title = Path(title.replace('\\', '/')).name[:250] or 'Dokumentacija'
    identity = hashlib.sha256(f'{tender.pk}:{tender.data.get("version", 1)}:{title}:{digest}'.encode()).hexdigest()[:32]
    existing = Document.objects.filter(pk=f'index-doc-{identity}').first()
    if existing:
        return existing
    reference = store(path, digest)
    return Document.objects.create(pk=f'index-doc-{identity}', tender=tender,
        version=tender.data.get('version', 1), title=title, sha256=digest, path=reference,
        status='processed' if archive else 'unprocessed', extraction={'mode': 'archive' if archive else 'unprocessed'})


def download(tender):
    meta = tender.data.get('source_metadata', {})
    url = meta.get('attachment_url')
    if not url or meta.get('access_restricted'):
        return
    download_key = hashlib.sha256(f'{tender.data.get("version", 1)}:{url}'.encode()).hexdigest()
    if meta.get('pipeline_download_key') == download_key and tender.document_records.filter(
            version=tender.data.get('version', 1)).exists():
        return
    with tempfile.TemporaryDirectory(prefix='razpizi-download-') as directory:
        root = Path(directory)
        path = root / 'download'
        digest, title = fetch_file(url, path)
        budget = {'members': 0, 'bytes': 0}

        def unpack(path, title, digest, depth=0):
            archive = zipfile.is_zipfile(path) and not title.lower().endswith(OFFICE)
            document = register(tender, path, title, digest, archive=archive)
            if not archive:
                return
            try:
                if depth > 2:
                    raise ValueError('Arhiv presega dovoljeno globino.')
                with zipfile.ZipFile(path) as handle:
                    for member in handle.infolist():
                        if member.is_dir():
                            continue
                        budget['members'] += 1
                        budget['bytes'] += member.file_size
                        if (budget['members'] > 5000 or budget['bytes'] > settings.PIPELINE_MAX_EXPANDED or
                                member.file_size > settings.PIPELINE_MAX_DOWNLOAD or member.flag_bits & 1 or
                                stat.S_ISLNK(member.external_attr >> 16)):
                            raise ValueError('Arhiv presega omejitve ali vsebuje zaščitene datoteke.')
                        # Names from the archive are never filesystem destinations.
                        target = root / f'member-{budget["members"]}'
                        with handle.open(member) as source:
                            sha = copy_stream(iter(lambda: source.read(1024 * 1024), b''), target,
                                              min(member.file_size, settings.PIPELINE_MAX_DOWNLOAD))
                        unpack(target, member.filename, sha, depth + 1)
                        target.unlink()
            except Exception:
                document.status = 'unprocessed'
                document.error = 'Arhiva ni bilo mogoče v celoti razpakirati; potreben je ponoven ali ročni pregled.'
                document.save(update_fields=['status', 'error'])
                raise
        unpack(path, title, digest)
    # Refresh before touching metadata; do not overwrite unrelated concurrent changes.
    tender.refresh_from_db()
    tender.data = {**tender.data, 'source_metadata': {**tender.data.get('source_metadata', {}),
                   'pipeline_download_key': download_key}}
    tender.save(update_fields=['data'])
