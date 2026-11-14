"""Evidence-backed review of an uploaded bid. Bid files never become tender sources."""
import hashlib
import html
import io
import logging
import re
import stat
import unicodedata
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .ai import provider, structured_call
from .deep_extract import extract_document
from .documents import active_documents, evidence_valid

log = logging.getLogger(__name__)
MAX_FILE = 50 * 1024**2
MAX_EXPANDED = 200 * 1024**2
MAX_FILES = 100
MAX_TEXT = 220_000
# Tender documentation goes only into the checklist call; the model has a ~1M token context.
MAX_SOURCE_TEXT = 600_000
# ESPD/UBL XML is mostly markup; the human-readable criteria live in Name/Description elements.
XML_TEXT = re.compile(r'<(?:[\w-]+:)?(?:Name|Description)\b[^>]*>([^<]+)</')
SUPPORTED = {'.pdf', '.docx', '.xlsx', '.pptx', '.odt', '.ods', '.txt', '.csv', '.xml', '.json'}


def obj(properties):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': list(properties)}


def array(items):
    return {'type': 'array', 'items': items}


TEXT = {'type': 'string'}
EVIDENCE = obj({'document_id': TEXT, 'page': {'type': 'integer'}, 'quote': TEXT})
CHECKLIST_SCHEMA = obj({'requirements': array(obj({'title': TEXT, 'requirement': TEXT,
    'category': {'type': 'string', 'enum': ['form', 'eligibility', 'technical', 'financial', 'submission', 'other']},
    'source': EVIDENCE}))})
REVIEW_SCHEMA = obj({'items': array(obj({'requirement_id': TEXT,
    'status': {'type': 'string', 'enum': ['covered', 'partial', 'missing', 'unknown', 'not_applicable']},
    'explanation': TEXT, 'action': TEXT, 'evidence': array(EVIDENCE)}))})


def read_uploads(uploads, prefix, folder=''):
    """Read bounded archives without extracting their paths. Flag every unreadable file."""
    if len(uploads) > MAX_FILES or sum(f.size for f in uploads) > MAX_FILE:
        raise ValidationError('Skupna velikost naloženih datotek je lahko največ 50 MB, največ 100 datotek.')
    docs, issues, seen, duplicates = [], [], set(), []
    total, count = 0, 0
    with TemporaryDirectory(prefix='razpizi-review-') as directory:
        def add(name, raw):
            nonlocal total, count
            count += 1
            total += len(raw)
            if count > MAX_FILES or len(raw) > MAX_FILE or total > MAX_EXPANDED:
                raise ValidationError('Arhiv presega omejitev: 100 datotek, 50 MB na datoteko, 200 MB razpakirane vsebine.')
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen:
                duplicates.append(name)
                return
            seen.add(digest)
            suffix = Path(name).suffix.lower()
            if suffix not in SUPPORTED:
                issues.append({'name': name, 'message': 'Nepodprt format; potreben je ročni pregled.'})
                return
            target = Path(directory) / (digest + suffix)
            target.write_bytes(raw)
            try:
                pages, kind = extract_document(target, name)
                if len(pages) > 150:
                    raise ValueError('Dokument presega 150 strani.')
                unreadable = [p['page'] for p in pages if len(p.get('text', '').strip()) < 20]
                if unreadable:
                    issues.append({'name': name, 'message': f'Strani brez dovolj berljivega besedila: {unreadable}. Potreben je OCR ali ročni pregled.'})
                docs.append({'id': f'{prefix}-{len(docs)+1}', 'name': name, 'format': kind, 'pages': pages})
            except Exception as exc:
                log.info('Bid extraction failed: %s', type(exc).__name__)
                issues.append({'name': name, 'message': 'Dokumenta ni mogoče v celoti prebrati; potreben je ročni pregled.'})

        for upload in uploads:
            raw = upload.read(MAX_FILE + 1)
            name = upload.name.replace('\\', '/')
            if len(raw) > MAX_FILE:
                raise ValidationError('Datoteka presega 50 MB.')
            if name.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        members = [m for m in archive.infolist() if not m.is_dir()
                                   and not m.filename.startswith('__MACOSX/') and Path(m.filename).name != '.DS_Store']
                        if prefix == 'bid':
                            if folder:
                                members = [m for m in members if str(Path(m.filename).parent).replace('\\', '/') == folder.strip('/')]
                                if not members:
                                    raise ValidationError('V izbrani mapi ZIP-a ni datotek. Navedite npr. PDF ali PDF/BREZ.')
                            else:
                                names = [Path(m.filename).name.casefold() for m in members]
                                if len(set(names)) != len(names):
                                    raise ValidationError('ZIP vsebuje istoimenske dokumente v več mapah, ki lahko predstavljajo različne prijave. V polju Mapa prijave v ZIP-u izberite eno mapo (npr. PDF ali PDF/BREZ), da se dokazila ne mešajo.')
                        if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_EXPANDED:
                            raise ValidationError('ZIP presega dovoljeno število ali velikost datotek.')
                        for member in members:
                            if member.file_size > MAX_FILE or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                                raise ValidationError('ZIP vsebuje preveliko, zaščiteno datoteko ali simbolno povezavo.')
                            # Member names are labels only; they never determine a filesystem path.
                            name = member.filename
                            if not member.flag_bits & 0x800:
                                try:
                                    name = name.encode('cp437').decode('utf-8')
                                except (UnicodeError, LookupError):
                                    pass
                            add(unicodedata.normalize('NFC', name), archive.read(member))
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError):
                    raise ValidationError('ZIP ni veljaven ali ga ni mogoče varno odpreti.')
            else:
                add(name, raw)
    if sum(len(p.get('text', '')) for d in docs for p in d['pages']) > MAX_TEXT:
        raise ValidationError('Besedila je preveč za en pregled (220.000 znakov). Izberite manjši sklop dokumentov.')
    return docs, issues, duplicates


def readable_pages(record, pages):
    fmt = record.indexed_content.format if record.indexed_content_id else ''
    if fmt != 'xml' and Path(record.title).suffix.lower() != '.xml':
        return pages
    readable = [{**p, 'text': '\n'.join(dict.fromkeys(
        line for line in (html.unescape(m).strip() for m in XML_TEXT.findall(p.get('text', ''))) if line))}
        for p in pages]
    return [p for p in readable if len(p['text']) >= 20]  # Pages of pure markup carry no requirement.


def tender_sources(tender):
    docs, issues = [], []
    records = active_documents(tender)
    for record in records:
        if record.extraction.get('mode') == 'archive':
            if record.status != 'processed':
                issues.append({'name': record.title, 'message': 'Razpisni arhiv ni v celoti obdelan.'})
            continue
        pages = readable_pages(record, record.indexed_content.pages if record.indexed_content_id else record.pages)
        if not pages or record.status != 'processed':
            issues.append({'name': record.title, 'message': 'Razpisni dokument ni v celoti berljiv.'})
        elif any(len(p.get('text', '').strip()) < 20 for p in pages):
            issues.append({'name': record.title, 'message': 'Del razpisnega dokumenta zahteva ročni pregled.'})
        docs.append({'id': record.pk, 'name': record.title, 'pages': pages})
    # Published answers/clarifications can change submission requirements.
    for question in tender.questions.exclude(answer=''):
        docs.append({'id': f'faq-{question.source_id}', 'name': 'Pojasnilo naročnika',
                     'pages': [{'page': 1, 'text': question.question + '\n' + question.answer}]})
    if not records:
        issues.append({'name': 'Razpisna dokumentacija', 'message': 'V razpisu ni shranjene dokumentacije. Dodajte uradne datoteke.'})
    return docs, issues


def valid_evidence(value, documents):
    if not isinstance(value, dict):
        return None
    doc = next((d for d in documents if d['id'] == value.get('document_id')), None)
    if not doc or not evidence_valid(doc['pages'], value.get('page'), value.get('quote')):
        return None
    return {**value, 'document_name': doc['name']}


def validate_checklist(answer, sources):
    requirements, seen = [], set()
    for item in answer['requirements']:
        proof = valid_evidence(item['source'], sources)
        if not proof or not item['title'].strip() or not item['requirement'].strip():
            raise ValueError('Requirement without source evidence')
        key = (item['requirement'].strip().casefold(), proof['document_id'], proof['page'])
        if key in seen:
            continue
        seen.add(key)
        requirements.append({**item, 'id': f'r{len(requirements)+1}', 'source': proof})
    if not requirements:
        raise ValueError('No verifiable requirements')
    return requirements


def validate_review(answer, requirements, submissions, incomplete):
    rows = {r['requirement_id']: r for r in answer['items']}
    expected = {r['id'] for r in requirements}
    if set(rows) != expected or len(rows) != len(answer['items']):
        raise ValueError('Incomplete or duplicate checklist response')
    output = []
    for requirement in requirements:
        row = rows[requirement['id']]
        proofs = [valid_evidence(e, submissions) for e in row['evidence']]
        status = row['status']
        explanation = row['explanation']
        if any(p is None for p in proofs) or (status in ('covered', 'partial', 'not_applicable') and not proofs):
            status, explanation = 'unknown', 'Dokaza za ugotovitev ni bilo mogoče potrditi v prijavi.'
        if status == 'missing' and incomplete:
            status, explanation = 'unknown', 'Dokaz ni najden v berljivem delu prijave; del datotek zahteva ročni pregled.'
        if status == 'covered' and re.search(r'podpis|žig|pravočas|kriptograf', requirement['requirement'], re.I):
            status = 'unknown'
            explanation += ' Podpis, žig oziroma dejansko pravočasno oddajo je treba dodatno preveriti ročno.'
        output.append({**requirement, 'status': status, 'explanation': explanation,
                       'action': row['action'], 'evidence': [p for p in proofs if p is not None]})
    return output


def review(tender, submissions, submission_issues, duplicates):
    if provider() != 'openrouter':
        raise ValidationError('Za pregled prijave nastavite OPENROUTER_API_KEY na strežniku.')
    sources, issues = tender_sources(tender)
    if sum(len(p.get('text', '')) for d in sources for p in d['pages']) > MAX_SOURCE_TEXT:
        raise ValidationError('Razpisna dokumentacija je za samodejni pregled predolga (več kot 600.000 znakov). '
                              'Na zavihku Dokumenti odstranite priloge, ki ne določajo zahtev za ponudbo (npr. risbe, popise), in poskusite znova.')
    if not any(p.get('text', '').strip() for d in sources for p in d['pages']):
        raise ValidationError('Najprej dodajte berljivo razpisno dokumentacijo na zavihku Dokumenti.')
    if not any(p.get('text', '').strip() for d in submissions for p in d['pages']):
        raise ValidationError('Prijava nima berljivega besedila. Potreben je OCR ali drug dokument.')
    model = settings.SUBMISSION_REVIEW_MODEL
    call = dict(model=model, max_tokens=16000, timeout=120)
    # Both calls must finish within the 300 s proxy timeout; the checklist reads the long tender text.
    checklist = structured_call(CHECKLIST_SCHEMA,
        'Sestavi kontrolni seznam VSEH izrecnih zahtev za popolnost oddane ponudbe iz uradne dokumentacije '
        'in pojasnil naročnika. Vključi zahtevane obrazce, priloge, dokazila, podpis/potrditev, izpolnjena polja, '
        'predračun, reference, tehnične zahteve, zavarovanja ter način in rok oddaje. Razlikuj kaj mora biti '
        'priloženo ob oddaji in kaj šele po izboru. Zapiši pogoje uporabe (npr. samo s podizvajalci), sklope '
        'in izjeme. Pojasnila lahko spremenijo prvotne zahteve. Vsaka zahteva mora imeti dobeseden citat, '
        'document_id in page iz priloženih virov. Piši slovensko. Ne izmišljaj zahtev.',
        {'tender': tender.data.get('title', ''), 'sources': sources}, **{**call, 'timeout': 160})
    requirements = validate_checklist(checklist, sources)
    result = structured_call(REVIEW_SCHEMA,
        'Primerjaj kontrolni seznam z dejansko pripravljeno prijavo. Vrni natanko eno vrstico za vsak '
        'requirement_id. covered pomeni vsebinsko pokrito z dokazom, partial delno, missing dokaz manjka, '
        'unknown ni mogoče preveriti, not_applicable dokazano ne velja za to ponudbo. Prisotnost datoteke '
        'ali prazen obrazec ne dokazuje izpolnitve. Preveri izpolnjenost polj, zneske, datume, identiteto '
        'ponudnika in skladnost dokumentov. Vsak covered/partial/not_applicable podpri z dobesednim citatom '
        'iz PRIJAVE (document_id/page/quote), nikoli iz razpisa. Podpisov, žigov, prečrtanih izbir, digitalnih '
        'podpisov in dejanske pravočasne oddaje iz besedila ni mogoče zanesljivo preveriti: unknown in '
        'konkreten korak ročnega pregleda. Ne sklepaj iz imena datoteke. Upoštevaj pogoje uporabe in '
        'dokazano odsotnost podizvajalcev. explanation utemelji, action pove konkretno dopolnitev. Piši slovensko.',
        {'requirements': requirements, 'submission_documents': submissions, 'unreadable': submission_issues}, **call)
    items = validate_review(result, requirements, submissions, bool(submission_issues))
    counts = {state: sum(i['status'] == state for i in items) for state in ('covered', 'partial', 'missing', 'unknown', 'not_applicable')}
    return {'mode': 'live', 'model': model, 'tender_id': tender.pk, 'version': tender.data.get('version', 1),
        'reviewed_at': timezone.now().isoformat(), 'items': items, 'counts': counts,
        'result': 'incomplete' if issues or submission_issues else 'needs_work' if any(counts[k] for k in ('partial', 'missing', 'unknown')) else 'covered',
        'source_issues': issues, 'submission_issues': submission_issues, 'duplicates': duplicates,
        'documents': [{'id': d['id'], 'name': d['name'], 'pages': len(d['pages'])} for d in submissions],
        'limitations': 'Predhodni AI pregled razpoložljivih dokumentov. Popolnost izluščenega seznama, podpise, veljavnost dokazil in dejansko oddajo preverite ročno.'}
