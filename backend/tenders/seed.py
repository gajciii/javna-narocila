from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import CompanyProfile, Tender, TenderVersion, SavedSearch, Notification, DemoEvent, Document


def today():
    return date.fromisoformat(settings.DEMO_DATE) if settings.DEMO_DATE else timezone.localdate()


def demo_profile():
    day = today()
    return {
        'id': 1, 'name': 'Lumina digital d.o.o.', 'registration_number': 'DEMO-001',
        'activity': 'Razvoj programske opreme in digitalnih rešitev',
        'address': 'Primerna ulica 12, 2000 Maribor', 'website': 'https://example.com',
        'description': 'Razvijamo spletne in mobilne aplikacije, IoT platforme ter podatkovne rešitve. Povezujemo senzorje in poslovne sisteme ter avtomatiziramo procese.',
        'expertise': ['Spletne platforme', 'IoT in integracije', 'AI in podatki'],
        'technologies': ['React', 'Django', 'ASP.NET', 'Vue.js', 'Nuxt.js', 'WebSocket', 'Docker'],
        'keywords': ['razvoj programske opreme', 'spletna platforma', 'IoT', 'integracija', 'podatkovna analitika', 'satelitski podatki'],
        'excluded_keywords': ['samo dobava licenc', 'dobava tiskalnikov'],
        'regions': ['Slovenija'], 'min_value': 20000, 'max_value': 350000,
        'available_from': day.isoformat(), 'staff_count': 6, 'certifications': [],
        'capacity': 'Ena razvojna ekipa, do dva vzporedna projekta.', 'source': 'demo',
        'references': [
            {'id': 'ref-energy', 'title': 'Energetski nadzor javnih objektov', 'description': 'Razvoj IoT nadzorne plošče in povezovanje senzorjev.', 'domain': 'energy', 'value': 120000, 'year': day.year - 1, 'confirmed': True},
            {'id': 'ref-sport', 'title': 'Platforma za športna tekmovanja', 'description': 'Spletna aplikacija za prijave, rezultate in upravljanje tekmovanj.', 'domain': 'sport', 'value': None, 'year': None, 'confirmed': True},
            {'id': 'ref-satellite', 'title': 'Analitika satelitskih posnetkov', 'description': 'Obdelava satelitskih podatkov in spremljanje vegetacije.', 'domain': 'satellite', 'value': 90000, 'year': day.year - 1, 'confirmed': True},
        ],
    }


def seed_tenders():
    day = today()
    def deadline(days):
        return datetime.combine(day + timedelta(days=days), time(12), tzinfo=ZoneInfo('Europe/Ljubljana')).isoformat()
    def item(id, title, buyer, region, value, days, summary, topics, tech, cpv, **extra):
        return {'id': id, 'title': title, 'buyer': buyer, 'region': region, 'kind': 'services',
                'value': value, 'deadline': deadline(days), 'published_at': (day - timedelta(days=2)).isoformat(),
                'status': 'open', 'source_type': 'demo', 'source_url': None, 'summary': summary,
                'description': summary, 'topics': topics, 'technologies': tech, 'cpv': cpv,
                'is_new': False, 'has_update': False, 'version': 1, 'criteria': [{'title': 'Cena', 'weight': 60}, {'title': 'Kakovost rešitve', 'weight': 40}],
                'lots': [], 'changes': [], **extra}
    return [
        item('energy-iot', 'IoT platforma za spremljanje porabe energije v javnih stavbah', 'Mestna občina Vzorčno', 'Podravska', 185000, 24,
             'Razvoj spletne platforme za zajem podatkov iz senzorjev, spremljanje porabe energije in opozarjanje na odstopanja. Vključuje API integracije, nadzorne plošče in usposabljanje uporabnikov.',
             ['IoT', 'spletna platforma', 'integracija', 'energetika'], ['React', 'Django', 'WebSocket'], ['72262000', '72316000']),
        item('sport-portal', 'Spletni portal za upravljanje športnih tekmovanj', 'Javni zavod Športni center Primer', 'Osrednjeslovenska', 98000, 18,
             'Vzpostavitev portala za prijave udeležencev, upravljanje tekmovanj in objavo rezultatov v realnem času. Zahtevana je zaključena primerljiva referenca v vrednosti najmanj 60.000 EUR v zadnjih treh letih.',
             ['spletna platforma', 'šport', 'integracija'], ['React', 'Django'], ['72230000']),
        item('satellite', 'Platforma za analizo satelitskih posnetkov in spremljanje vegetacije', 'Inštitut za okoljske podatke – demo', 'Slovenija', 240000, 32,
             'Obdelava satelitskih posnetkov, zaznavanje sprememb vegetacije in prikaz rezultatov v spletni aplikaciji. Razpis vključuje razvoj podatkovnega cevovoda in API-ja.',
             ['podatkovna analitika', 'AI', 'satelitski podatki', 'spletna platforma'], ['Django', 'React', 'Docker'], ['72316000', '72262000']),
        item('office-licenses', 'Podaljšanje licenc pisarniške programske opreme', 'Upravni center Primer', 'Savinjska', 28000, 12,
             'Dobava in podaljšanje 150 standardnih pisarniških licenc za obdobje enega leta. Razvoj programske opreme, integracije in prilagoditve niso predmet naročila.',
             ['dobava licenc', 'pisarniška oprema'], [], ['48000000'], kind='goods', criteria=[{'title': 'Cena', 'weight': 100}]),
        item('lab-platform', 'Digitalizacija laboratorija: oprema in povezovalna platforma', 'Raziskovalni laboratorij Primer', 'Gorenjska', None, 27,
             'Naročilo je razdeljeno na dobavo laboratorijske opreme in razvoj povezovalne platforme. Ponudbo je mogoče oddati za posamezen sklop. Za razvojni sklop so pomembni zajem podatkov, integracije in sledljivost vzorcev.',
             ['IoT', 'integracija', 'spletna platforma', 'avtomatizacija'], ['Django', 'WebSocket'], ['72262000', '38000000'],
             lots=[{'id': 'lab-hardware', 'title': 'Sklop 1: laboratorijska oprema', 'match_level': 'low', 'summary': 'Dobava merilne in laboratorijske opreme.', 'topics': ['dobava opreme']}, {'id': 'lab-software', 'title': 'Sklop 2: povezovalna platforma', 'match_level': 'high', 'summary': 'Razvoj platforme za zajem podatkov, integracije in poročanje.', 'topics': ['IoT', 'integracija', 'spletna platforma']}]),
        item('municipal-app', 'Mobilna aplikacija za občinske storitve', 'Občina Zelena dolina – demo', 'Savinjska', 68000, -9,
             'Razvoj mobilne aplikacije za obveščanje občanov, prijavo pobud in spremljanje občinskih storitev.',
             ['mobilne aplikacije', 'spletna platforma'], ['React'], ['72230000'], status='closed', published_at=(day - timedelta(days=40)).isoformat()),
        item('ijs-archive', 'Razvoj in vzdrževanje spletne platforme IJS z informacijskim in uredniškim sistemom', 'Institut Jožef Stefan', 'Osrednjeslovenska', None, -1,
             'Resnični arhivski zapis: razvoj in vzdrževanje spletne platforme IJS z informacijskim in uredniškim sistemom. Uradni e-JN navaja stanje Ustavljeno. Pogoji iz priponk v tem demo zapisu niso analizirani.',
             ['spletna platforma', 'informacijski sistem'], [], [], status='cancelled', source_type='real',
             source_url='https://www.enarocanje.si/#/pregled-objav/1144799?d=1',
             published_at=None, deadline='2026-09-07T10:00:00+02:00', criteria=[],
             source_metadata={'notice_number': 'JN006195/2026-EUe16/01', 'verified_fields': ['title', 'buyer', 'deadline', 'status'], 'publication_date_verified': False, 'url': 'https://ejn.gov.si/ponudba/pages/aktualno/aktualno_jnc_podrobno.xhtml?zadevaId=77669'}),
    ]


@transaction.atomic
def ensure_seed(reset=False):
    if reset:
        Notification.objects.all().delete()
        DemoEvent.objects.all().delete()
        SavedSearch.objects.all().delete()
        Tender.objects.all().delete()
        CompanyProfile.objects.all().delete()
    if not CompanyProfile.objects.filter(pk=1).exists():
        CompanyProfile.objects.create(pk=1, data=demo_profile())
    if not Tender.objects.exists():
        for data in seed_tenders():
            tender = Tender.objects.create(id=data['id'], data=data, following=data['id'] in ['satellite', 'sport-portal'])
            TenderVersion.objects.create(tender=tender, version=1, data=data)
        SavedSearch.objects.create(name='Digitalne priložnosti', filters={'q': 'spletna platforma, integracija, IoT', 'statuses': ['open'], 'min_days': 14, 'view': 'all', 'include_unknown': True})
    from .documents import load_demo_documents
    load_demo_documents()


def get_profile():
    record = CompanyProfile.objects.get(pk=1)
    return {**record.data, 'id': 1, 'updated_at': record.updated_at.isoformat()}
