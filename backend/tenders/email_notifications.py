"""Durable SMTP/Resend outbox for followed changes and new-tender digests."""
import logging
import re
from datetime import datetime, time, timedelta
from email.utils import parseaddr
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import requests

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .accounts import account_id
from .models import (EMAIL_TYPES, EmailNotificationSettings, Notification, NotificationEmail,
                     Tender, TenderDigestEmail, TenderFollow)

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
DIGEST_FREQUENCIES = ('daily', 'weekly')


def next_digest_at(now, frequency):
    """Next 08:00 in Slovenia; weekly digests go out on Monday."""
    local = now.astimezone(ZoneInfo(settings.TIME_ZONE))
    day = local.date()
    if frequency == 'weekly':
        day += timedelta(days=(7 - day.weekday()) % 7)
    candidate = datetime.combine(day, time(8), tzinfo=ZoneInfo(settings.TIME_ZONE))
    if candidate <= local:
        candidate += timedelta(days=7 if frequency == 'weekly' else 1)
    return candidate


def transport_ready():
    try:
        validate_email(parseaddr(settings.DEFAULT_FROM_EMAIL)[1])
    except DjangoValidationError:
        return False
    if not settings.PUBLIC_APP_URL:
        return False
    if settings.EMAIL_PROVIDER == 'resend':
        return bool(settings.RESEND_API_KEY)
    return bool(settings.EMAIL_PROVIDER == 'smtp' and settings.EMAIL_HOST and not
                (settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL))


def status():
    config, _ = EmailNotificationSettings.objects.get_or_create(owner_id=account_id())
    deliveries = NotificationEmail.objects.filter(owner_id=account_id())
    digests = TenderDigestEmail.objects.filter(owner_id=account_id())
    last = max(filter(None, (deliveries.aggregate(sent=Max('sent_at'))['sent'],
                             digests.aggregate(sent=Max('sent_at'))['sent'])), default=None)
    account_email = getattr(getattr(config, 'owner', None), 'email', '') or ''
    return {'enabled': config.enabled, 'email': config.email, 'account_email': account_email,
            'types': [t for t in EMAIL_TYPES if t in config.types],
            'digest_enabled': config.digest_enabled, 'digest_frequency': config.digest_frequency,
            'digest_next_at': config.digest_next_at.isoformat() if config.digest_next_at else None,
            'transport_ready': transport_ready(),
            'provider': settings.EMAIL_PROVIDER if settings.EMAIL_PROVIDER in ('smtp', 'resend') else 'unavailable',
            'pending': deliveries.filter(state='pending').count() + digests.filter(state='pending').count(),
            'failed': deliveries.filter(state='failed').count() + digests.filter(state='failed').count(),
            'last_sent_at': last.isoformat() if last else None}


@transaction.atomic
def save_settings(data):
    email, enabled = data.get('email', ''), data.get('enabled')
    if not isinstance(enabled, bool):
        raise ValidationError({'enabled': 'Izberite, ali želite e-poštna obvestila.'})
    types = data.get('types', list(EMAIL_TYPES))
    if not isinstance(types, list) or not all(isinstance(t, str) and t in EMAIL_TYPES for t in types):
        raise ValidationError({'types': 'Izberite veljavne vrste obvestil.'})
    types = [t for t in EMAIL_TYPES if t in types]
    if not isinstance(email, str) or len(email) > 254:
        raise ValidationError({'email': 'Vnesite veljaven e-poštni naslov.'})
    email = email.strip()
    if email or enabled:
        try:
            validate_email(email)
        except DjangoValidationError:
            raise ValidationError({'email': 'Vnesite veljaven e-poštni naslov.'})
    config, _ = EmailNotificationSettings.objects.get_or_create(owner_id=account_id())
    config = EmailNotificationSettings.objects.select_for_update().get(pk=config.pk)
    digest_enabled = data.get('digest_enabled', config.digest_enabled)
    frequency = data.get('digest_frequency', config.digest_frequency)
    if not isinstance(digest_enabled, bool):
        raise ValidationError({'digest_enabled': 'Izberite, ali želite prejemati nove razpise.'})
    if frequency not in DIGEST_FREQUENCIES:
        raise ValidationError({'digest_frequency': 'Izberite dnevno ali tedensko pošiljanje.'})
    if enabled and not types and not digest_enabled:
        raise ValidationError({'types': 'Izberite vsaj eno vrsto obvestil ali izklopite e-poštna obvestila.'})
    changed = config.email != email or config.enabled != enabled
    digest_changed = config.digest_enabled != digest_enabled or config.digest_frequency != frequency
    if changed:
        # No old notifications are mailed after enabling or changing the recipient.
        config.enabled_since = timezone.now() if enabled else None
        NotificationEmail.objects.filter(owner_id=account_id(), state__in=['pending', 'failed']).update(state='cancelled')
        TenderDigestEmail.objects.filter(owner_id=account_id(), state__in=['pending', 'failed']).update(state='cancelled')
        config.digest_cursor_at = config.enabled_since if enabled and digest_enabled else None
        config.digest_next_at = next_digest_at(config.enabled_since, frequency) if enabled and digest_enabled else None
    elif removed := set(config.types) - set(types):
        # Messages of a type the user no longer wants are not sent.
        NotificationEmail.objects.filter(owner_id=account_id(), state__in=['pending', 'failed'],
                                         notification__type__in=removed).update(state='cancelled')
    if not changed and digest_changed:
        outstanding = TenderDigestEmail.objects.filter(owner_id=account_id(), state__in=['pending', 'failed'])
        earliest = outstanding.aggregate(start=Min('period_start'))['start']
        outstanding.update(state='cancelled')
        if enabled and digest_enabled:
            if not config.digest_enabled:
                config.digest_cursor_at = timezone.now()
            elif earliest and (not config.digest_cursor_at or earliest < config.digest_cursor_at):
                config.digest_cursor_at = earliest
            elif not config.digest_cursor_at:
                config.digest_cursor_at = timezone.now()
            config.digest_next_at = next_digest_at(timezone.now(), frequency)
        else:
            config.digest_cursor_at = config.digest_next_at = None
    config.email, config.enabled, config.types = email, enabled, types
    config.digest_enabled, config.digest_frequency = digest_enabled, frequency
    config.save()
    return status()


def message(notification):
    tender = notification.tender
    title = re.sub(r'\s+', ' ', tender.data.get('title') or 'Razpis').strip()
    kind = 'Sprememba roka' if notification.type == 'deadline' else 'Sprememba razpisa'
    subject = f'RazpIzi · {kind}: {title}'[:250]
    link = f'{settings.PUBLIC_APP_URL}/#/razpisi/{quote(tender.pk, safe="")}?tab=changes'
    body = (f'{kind}\n\n{title}\nNaročnik: {tender.data.get("buyer", "")}\n\n'
            f'{notification.body}\n\nPreglejte spremembe in izvorne pogoje:\n{link}\n\n'
            f'Obvestilo je nastalo ob zajemu {timezone.localtime(notification.created_at):%d. %m. %Y ob %H:%M}.\n'
            f'Prejemate ga, ker spremljate ta razpis in imate vključena e-poštna obvestila. '
            f'Naslov in vrste obvestil uredite v Moj račun:\n{settings.PUBLIC_APP_URL}/#/racun\n')
    return subject, body


@transaction.atomic
def enqueue(limit=100):
    if not transport_ready():
        return 0
    count = 0
    for config in EmailNotificationSettings.objects.select_for_update().filter(enabled=True, enabled_since__isnull=False):
        if config.owner_id is not None:
            if not config.owner.is_active:
                continue
            followed = TenderFollow.objects.filter(owner_id=config.owner_id).values('tender_id')
            follow_filter = {'tender_id__in': followed}
        else:
            follow_filter = {'tender__following': True}
        delivered = NotificationEmail.objects.filter(owner_id=config.owner_id).values('notification_id')
        notifications = Notification.objects.select_related('tender').filter(
            is_demo=False, active=True, type__in=[t for t in config.types if t in EMAIL_TYPES],
            tender__data__source_type='real', created_at__gte=config.enabled_since,
            **follow_filter).exclude(pk__in=delivered).order_by('created_at', 'pk')[:max(0, limit - count)]
        for notification in notifications:
            subject, body = message(notification)
            _, created = NotificationEmail.objects.get_or_create(notification=notification, owner_id=config.owner_id,
                defaults={'recipient': config.email, 'sender': settings.DEFAULT_FROM_EMAIL, 'subject': subject, 'body': body})
            count += created
    return count


def digest_message(matches, frequency):
    label = 'Dnevni' if frequency == 'daily' else 'Tedenski'
    subject = f'RazpIzi · {label.lower()} pregled novih razpisov ({len(matches)})'
    lines = [f'{label} pregled novih primernih razpisov', '',
             f'Novi odprti razpisi za vaš trenutni profil: {len(matches)}.',
             'Pogoje in dokumentacijo preverite pred odločitvijo za prijavo.', '']
    for tender in matches[:100]:
        lines.extend([f'• {tender["title"]} — {tender["buyer"]}',
                      f'  {settings.PUBLIC_APP_URL}/#/razpisi/{quote(tender["id"], safe="")}', ''])
    if len(matches) > 100:
        lines.extend([f'Prikazanih je prvih 100 od {len(matches)} razpisov. Vse preglejte v aplikaciji:',
                      f'{settings.PUBLIC_APP_URL}/#/razpisi', ''])
    lines.extend(['Pogostost pošiljanja uredite v Moj račun:', f'{settings.PUBLIC_APP_URL}/#/racun'])
    return subject[:250], '\n'.join(lines)


def digest_matches(period_start, period_end):
    """Use the current account's profile and exclusions for both scheduled and test digests."""
    from .accounts import companies
    from .matching import serialize_tender
    from .seed import serialize_profile

    profile_record = companies().filter(is_active=True).first() or companies().order_by('pk').first()
    profile = serialize_profile(profile_record) if profile_record else None
    matches = []
    if profile:
        candidates = Tender.objects.filter(data__source_type='real', created_at__gte=period_start,
                                           created_at__lt=period_end).order_by('created_at', 'pk')
        for tender in candidates.iterator():
            result = serialize_tender(tender, profile, content_result={'mode': 'rules'})
            if (result['status'] == 'open' and result['match']['level'] != 'low'
                    and result['match']['recommendation'] != 'unsuitable' and not result['ignored']):
                matches.append(result)
    return matches


@transaction.atomic
def enqueue_digests(now=None):
    """Queue at most one digest per account when its local daily or weekly slot is due."""
    if not transport_ready():
        return 0
    from .accounts import account_scope

    now = now or timezone.now()
    count = 0
    configs = EmailNotificationSettings.objects.select_for_update().filter(enabled=True, digest_enabled=True)
    for config in configs:
        if config.owner_id is not None and not config.owner.is_active:
            continue
        if not config.digest_cursor_at or not config.digest_next_at:
            # Existing subscribers start fresh after the migration; no historical backfill.
            config.digest_cursor_at = now
            config.digest_next_at = next_digest_at(now, config.digest_frequency)
            config.save(update_fields=['digest_cursor_at', 'digest_next_at'])
            continue
        if config.digest_next_at > now:
            continue
        with account_scope(config.owner_id):
            matches = digest_matches(config.digest_cursor_at, now)
        if matches:
            subject, body = digest_message(matches, config.digest_frequency)
            TenderDigestEmail.objects.create(owner_id=config.owner_id, recipient=config.email,
                sender=settings.DEFAULT_FROM_EMAIL, subject=subject, body=body,
                period_start=config.digest_cursor_at, period_end=now,
                tender_ids=[item['id'] for item in matches])
            count += 1
        config.digest_cursor_at = now
        config.digest_next_at = next_digest_at(now, config.digest_frequency)
        config.save(update_fields=['digest_cursor_at', 'digest_next_at'])
    return count


class ProviderRejected(RuntimeError):
    """The provider answered but did not accept the message; `detail` is its own short explanation."""
    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def transmit(sender, recipient, subject, body, headers, idempotency_key):
    if settings.EMAIL_PROVIDER == 'resend':
        response = requests.post('https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}', 'Idempotency-Key': idempotency_key},
            json={'from': sender, 'to': [recipient], 'subject': subject, 'text': body, 'headers': headers},
            timeout=settings.EMAIL_TIMEOUT, allow_redirects=False)
        if response.status_code >= 400:
            try:
                detail = response.json().get('message') or ''
            except ValueError:
                detail = ''
            response.reason = (detail or response.reason or '')[:300]
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise RuntimeError('Resend did not accept the message')
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not data['id'].strip():
            raise RuntimeError('Resend did not return a message identifier')
    else:
        sent = EmailMessage(subject, body, sender, [recipient], headers=headers).send(fail_silently=False)
        if sent != 1:
            raise RuntimeError('SMTP did not accept the message')


def send(delivery):
    host = urlsplit(settings.PUBLIC_APP_URL).hostname
    transmit(delivery.sender, delivery.recipient, delivery.subject, delivery.body,
             {'Message-ID': f'<razpizi-notification-{delivery.notification_id}@{host}>'},
             f'notification/{delivery.delivery_key}/{delivery.pk}')


def send_digest(delivery):
    host = urlsplit(settings.PUBLIC_APP_URL).hostname
    transmit(delivery.sender, delivery.recipient, delivery.subject, delivery.body,
             {'Message-ID': f'<razpizi-digest-{delivery.pk}@{host}>'},
             f'digest/{delivery.delivery_key}/{delivery.pk}')


def missing_settings():
    """Server settings that still prevent sending, named as they are set in the deployment."""
    missing = []
    if settings.EMAIL_PROVIDER not in ('smtp', 'resend'):
        missing.append('EMAIL_PROVIDER (smtp ali resend)')
    elif settings.EMAIL_PROVIDER == 'resend' and not settings.RESEND_API_KEY:
        missing.append('RESEND_API_KEY')
    elif settings.EMAIL_PROVIDER == 'smtp':
        if not settings.EMAIL_HOST:
            missing.append('EMAIL_HOST')
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
            missing.append('EMAIL_USE_TLS in EMAIL_USE_SSL ne smeta biti oba vključena')
    try:
        validate_email(parseaddr(settings.DEFAULT_FROM_EMAIL)[1])
    except DjangoValidationError:
        missing.append('DEFAULT_FROM_EMAIL')
    if not settings.PUBLIC_APP_URL:
        missing.append('PUBLIC_APP_URL')
    return missing


def send_test(kind='connection'):
    """Send one test message to the saved recipient (or the login address) and say what happened."""
    from uuid import uuid4
    if kind not in ('connection', *DIGEST_FREQUENCIES):
        raise ValidationError({'kind': 'Izberite test povezave, dnevnega ali tedenskega pregleda.'})
    config, _ = EmailNotificationSettings.objects.get_or_create(owner_id=account_id())
    recipient = config.email or (config.owner.email if config.owner else '')
    if not recipient:
        return {'sent': False, 'message': 'Najprej shranite e-poštni naslov prejemnika.'}
    missing = missing_settings()
    if missing:
        return {'sent': False, 'message': 'Pošiljanje na strežniku še ni nastavljeno. Manjka: ' + ', '.join(missing) + '.'}
    host = urlsplit(settings.PUBLIC_APP_URL).hostname
    token = uuid4().hex
    provider = 'Resend' if settings.EMAIL_PROVIDER == 'resend' else 'SMTP'
    body = (f'To je testno sporočilo iz aplikacije RazpIzi.\n\n'
            f'Če ga berete, pošiljanje prek {provider} deluje in boste prejemali izbrana obvestila '
            f'o spremembah in novih primernih razpisih.\n\nNastavitve: {settings.PUBLIC_APP_URL}/#/racun\n')
    subject = 'RazpIzi · Testno sporočilo'
    if kind in DIGEST_FREQUENCIES:
        now = timezone.now()
        matches = digest_matches(now - timedelta(days=1 if kind == 'daily' else 7), now)
        subject, body = digest_message(matches, kind)
        subject = f'[TEST] {subject}'
        body = ('To je testni pregled za zadnjih ' + ('24 ur' if kind == 'daily' else '7 dni')
                + '. Redni urnik pošiljanja ostaja nespremenjen.\n\n' + body)
        if not matches:
            body += '\n\nV tem obdobju ni novih primernih razpisov za vaš aktivni profil. Redni pregled se v tem primeru ne pošlje.'
    try:
        transmit(settings.DEFAULT_FROM_EMAIL, recipient, subject, body,
                 {'Message-ID': f'<razpizi-test-{token}@{host}>'}, f'test/{token}')
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else ''
        detail = exc.response.reason if exc.response is not None else ''
        log.warning('Test email rejected by %s: %s', provider, status_code)
        return {'sent': False, 'message': f'{provider} sporočila ni sprejel ({status_code}). {detail}'.strip()}
    except Exception as exc:
        log.warning('Test email failed: %s', type(exc).__name__)
        return {'sent': False, 'message': f'Pošiljanje prek {provider} ni uspelo ({type(exc).__name__}). Preverite nastavitve na strežniku.'}
    label = {'connection': 'Testno sporočilo', 'daily': 'Testni dnevni pregled', 'weekly': 'Testni tedenski pregled'}[kind]
    return {'sent': True, 'message': f'{label}: sporočilo je predano v pošiljanje na {recipient}. Preverite tudi vsiljeno pošto.'}


@transaction.atomic
def deliver(delivery_id):
    # Lock order matches preference updates. Delivery runs outside request handling.
    owner = NotificationEmail.objects.values_list('owner_id', flat=True).get(pk=delivery_id)
    config = EmailNotificationSettings.objects.select_for_update().filter(owner_id=owner).first()
    delivery = NotificationEmail.objects.select_for_update(of=('self',)).select_related('notification__tender').get(pk=delivery_id)
    if delivery.state != 'pending' or delivery.available_at > timezone.now():
        return False
    notification = delivery.notification
    if (not config or not config.enabled or config.email != delivery.recipient or not config.enabled_since
            or notification.created_at < config.enabled_since or not notification.active or notification.is_demo
            or notification.type not in ('correction', 'deadline') or not notification.tender
            or (not TenderFollow.objects.filter(owner_id=owner, tender=notification.tender).exists() if owner is not None else not notification.tender.following)
            or (owner is not None and not config.owner.is_active) or notification.tender.data.get('source_type') != 'real'):
        delivery.state = 'cancelled'
        delivery.save(update_fields=['state'])
        return False
    if not transport_ready():
        return False
    delivery.attempts += 1
    # Existing outbox rows from before sender snapshots acquire it on their first new attempt.
    delivery.sender = delivery.sender or settings.DEFAULT_FROM_EMAIL
    try:
        send(delivery)
    except Exception as exc:
        # Provider errors can include addresses or server details; expose only a generic status.
        log.warning('Notification email delivery failed (%s)', type(exc).__name__)
        delivery.error = 'Pošiljanje ni uspelo. Preverite nastavitve pošiljanja e-pošte.'
        delivery.state = 'failed' if delivery.attempts >= MAX_ATTEMPTS else 'pending'
        delivery.available_at = timezone.now() + timedelta(seconds=min(3600, 60 * 2 ** (delivery.attempts - 1)))
    else:
        delivery.state, delivery.sent_at, delivery.error = 'sent', timezone.now(), ''
    delivery.save(update_fields=['state', 'attempts', 'sent_at', 'error', 'available_at', 'sender'])
    return delivery.state == 'sent'


@transaction.atomic
def deliver_digest(delivery_id):
    owner = TenderDigestEmail.objects.values_list('owner_id', flat=True).get(pk=delivery_id)
    config = EmailNotificationSettings.objects.select_for_update().filter(owner_id=owner).first()
    delivery = TenderDigestEmail.objects.select_for_update().get(pk=delivery_id)
    if delivery.state != 'pending' or delivery.available_at > timezone.now():
        return False
    if (not config or not config.enabled or not config.digest_enabled or config.email != delivery.recipient
            or (owner is not None and not config.owner.is_active)):
        delivery.state = 'cancelled'
        delivery.save(update_fields=['state'])
        return False
    if not transport_ready():
        return False
    delivery.attempts += 1
    try:
        send_digest(delivery)
    except Exception as exc:
        log.warning('Tender digest delivery failed (%s)', type(exc).__name__)
        delivery.error = 'Pošiljanje ni uspelo. Preverite nastavitve pošiljanja e-pošte.'
        delivery.state = 'failed' if delivery.attempts >= MAX_ATTEMPTS else 'pending'
        delivery.available_at = timezone.now() + timedelta(seconds=min(3600, 60 * 2 ** (delivery.attempts - 1)))
    else:
        delivery.state, delivery.sent_at, delivery.error = 'sent', timezone.now(), ''
    delivery.save(update_fields=['state', 'attempts', 'sent_at', 'error', 'available_at'])
    return delivery.state == 'sent'


def process(limit=20):
    enqueue()
    enqueue_digests()
    ids = list(NotificationEmail.objects.filter(state='pending', available_at__lte=timezone.now())
               .order_by('available_at', 'pk').values_list('pk', flat=True)[:limit])
    sent = sum(deliver(pk) for pk in ids)
    digest_ids = list(TenderDigestEmail.objects.filter(state='pending', available_at__lte=timezone.now())
                      .order_by('available_at', 'pk').values_list('pk', flat=True)[:max(0, limit - len(ids))])
    return sent + sum(deliver_digest(pk) for pk in digest_ids)
