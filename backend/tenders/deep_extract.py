"""Bounded text extraction for archived PJN attachments; no synthetic page claims."""
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .documents import extract_pages
from django.conf import settings

MAX_DOCUMENT = 50 * 1024 * 1024
MAX_XML = 15 * 1024 * 1024
MAX_TEXT = 2_000_000


def local(tag):
    return tag.rsplit('}', 1)[-1]


def xml_root(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML:
        raise ValueError('XML-del priloge presega omejitev.')
    return ET.fromstring(archive.read(name))


def text_nodes(element):
    return ''.join((node.text or '') for node in element.iter() if local(node.tag) == 't')


def blocks(lines, label, size=12000):
    pages, current, length, part = [], [], 0, 1
    for line in lines:
        line = re.sub(r'\s+', ' ', line).strip()
        if not line:
            continue
        if length + len(line) > size and current:
            pages.append({'page': len(pages) + 1, 'locator': f'{label}, del {part}', 'text': '\n'.join(current)})
            current, length, part = [], 0, part + 1
        current.append(line[:size])
        length += len(line) + 1
    if current:
        pages.append({'page': len(pages) + 1, 'locator': f'{label}, del {part}', 'text': '\n'.join(current)})
    return pages


def extract_office(path, suffix):
    with zipfile.ZipFile(path) as archive:
        files = archive.namelist()
        if len(files) > 500 or sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('Office priloga presega omejitve obdelave.')
        pages = []
        if suffix == '.docx':
            names = [n for n in files if re.fullmatch(r'word/(?:document|header\d+|footer\d+)\.xml', n)]
            for name in names:
                root = xml_root(archive, name)
                lines = (text_nodes(node) for node in root.iter() if local(node.tag) == 'p')
                pages.extend(blocks(lines, name))
        elif suffix == '.xlsx':
            shared = []
            if 'xl/sharedStrings.xml' in files:
                root = xml_root(archive, 'xl/sharedStrings.xml')
                shared = [text_nodes(node) for node in root.iter() if local(node.tag) == 'si']
            for name in sorted(n for n in files if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n)):
                root = xml_root(archive, name)
                lines = []
                for row in root.iter():
                    if local(row.tag) != 'row':
                        continue
                    cells = []
                    for cell in row:
                        if local(cell.tag) != 'c':
                            continue
                        value = next((n.text or '' for n in cell.iter() if local(n.tag) == 'v'), '')
                        if cell.attrib.get('t') == 's' and value.isdigit() and int(value) < len(shared):
                            value = shared[int(value)]
                        elif cell.attrib.get('t') == 'inlineStr':
                            value = text_nodes(cell)
                        if value:
                            cells.append(f"{cell.attrib.get('r', '')}: {value}")
                    if cells:
                        lines.append(' | '.join(cells))
                pages.extend(blocks(lines, name))
        elif suffix == '.pptx':
            for name in sorted(n for n in files if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)):
                root = xml_root(archive, name)
                pages.extend(blocks([text_nodes(root)], name))
        elif suffix in ('.odt', '.ods'):
            root = xml_root(archive, 'content.xml')
            lines = (''.join(node.itertext()) for node in root.iter() if local(node.tag) in ('p', 'h'))
            pages.extend(blocks(lines, 'content.xml'))
        else:
            raise ValueError('Nepodprt Office format.')
    for number, page in enumerate(pages, 1):
        page['page'] = number
    return pages


def extract_document(path, title):
    path = Path(path)
    max_document = settings.PIPELINE_MAX_DOCUMENT if settings.PIPELINE_REMOTE else MAX_DOCUMENT
    if path.stat().st_size > max_document:
        raise ValueError('Priloga presega omejitev 50 MB.')
    suffix = Path(title).suffix.lower()
    with path.open('rb') as handle:
        pdf = handle.read(5) == b'%PDF-'
    if pdf:
        pages = extract_pages(path, max_bytes=max_document,
            max_pages=settings.PIPELINE_MAX_PAGES if settings.PIPELINE_REMOTE else 500)
        return pages, 'pdf'
    if suffix in ('.docx', '.xlsx', '.pptx', '.odt', '.ods'):
        return extract_office(path, suffix), suffix[1:]
    if suffix in ('.txt', '.csv', '.xml', '.json'):
        raw = path.read_bytes()
        if b'\x00' in raw[:4096] or len(raw) > MAX_TEXT:
            raise ValueError('Besedilna priloga je prevelika ali vsebuje binarne podatke.')
        for encoding in ('utf-8-sig', 'cp1250'):
            try:
                return blocks(raw.decode(encoding).splitlines(), suffix[1:]), suffix[1:]
            except UnicodeDecodeError:
                pass
    raise ValueError('Format ni podprt za samodejno branje; potreben je ročni pregled.')


def process_document(document):
    if document.extraction.get('mode') == 'archive':
        return document
    if document.status == 'processed' and document.pages:
        return document
    try:
        pages, kind = extract_document(document.path, document.title)
        if sum(len(p['text'].strip()) for p in pages) < 20:
            raise ValueError('Priloga nima berljivega besedila; potreben je OCR ali ročni pregled.')
        document.pages = pages
        document.status = 'processed'
        document.error = ''
        document.extraction = {**document.extraction, 'format': kind, 'mode': 'unprocessed'}
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        document.status = 'unprocessed'
        document.error = str(exc)[:300]
    document.save(update_fields=['pages', 'status', 'error', 'extraction'])
    return document
