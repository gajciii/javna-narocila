"""Email-safe HTML layouts; all tender and notification content is autoescaped."""
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.template import Context, Engine

_engine = Engine(dirs=[Path(__file__).parent / 'templates'])


def render_email(*, title, intro, eyebrow, cards=(), notice='', detail='', action='Odpri razpise', action_url=None):
    return _engine.get_template('tenders/email/message.html').render(Context({
        'title': title, 'intro': intro, 'eyebrow': eyebrow, 'cards': cards,
        'notice': notice, 'detail': detail, 'action': action,
        'action_url': action_url or f'{settings.PUBLIC_APP_URL}/#/razpisi',
        'account_url': f'{settings.PUBLIC_APP_URL}/#/racun',
    }))


def digest_html(matches, frequency, *, test=False):
    label = 'Dnevni' if frequency == 'daily' else 'Tedenski'
    cards = [{
        'title': item['title'], 'buyer': item['buyer'],
        'url': f'{settings.PUBLIC_APP_URL}/#/razpisi/{quote(item["id"], safe="")}',
    } for item in matches[:100]]
    notice = ''
    if test:
        period = '24 ur' if frequency == 'daily' else '7 dni'
        notice = f'Testni pregled · zadnjih {period}. Redni urnik pošiljanja ostaja nespremenjen.'
    return render_email(
        title=f'{label} pregled razpisov', eyebrow='NOVI PRIMERNI RAZPISI',
        intro=f'Novi odprti razpisi za vaš trenutni profil: {len(matches)}.',
        cards=cards, notice=notice,
        detail=(f'Prikazanih je prvih 100 od {len(matches)} razpisov. Vse preglejte v aplikaciji.'
                if len(matches) > 100 else
                'Pogoje in dokumentacijo preverite pred odločitvijo za prijavo.' if matches else
                'V tem obdobju ni novih primernih razpisov za vaš aktivni profil. Redni pregled se v tem primeru ne pošlje.'),
        action='Preglej vse razpise')


def notification_html(notification):
    tender = notification.tender
    kind = 'Sprememba roka' if notification.type == 'deadline' else 'Sprememba razpisa'
    return render_email(
        title=kind, eyebrow='SPREMLJANI RAZPIS',
        intro='Pri razpisu, ki ga spremljate, smo zaznali spremembo.',
        cards=[{'title': tender.data.get('title') or 'Razpis', 'buyer': tender.data.get('buyer', ''),
                'body': notification.body}],
        detail='Pred odločitvijo preverite spremembe in izvorne pogoje razpisa.',
        action='Preglej spremembe',
        action_url=f'{settings.PUBLIC_APP_URL}/#/razpisi/{quote(tender.pk, safe="")}?tab=changes')


def connection_html():
    return render_email(
        title='Vaša povezava deluje.', eyebrow='TESTNO SPOROČILO',
        intro='Če berete to sporočilo, je testna e-pošta uspešno prispela do vas.',
        detail='Vrste obvestil, naslov prejemnika in pogostost pregledov lahko uredite v svojem računu.',
        notice='To je test povezave. Redna obvestila se pošiljajo glede na vaše shranjene nastavitve.',
        action='Uredi obvestila', action_url=f'{settings.PUBLIC_APP_URL}/#/racun')
