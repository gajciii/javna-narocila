"""Durable SMTP/Resend outbox for future changes of followed, real tenders."""
import logging
import re
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import quote, urlsplit

import requests

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .accounts import account_id
from .models import EmailNotificationSettings, Notification, NotificationEmail, TenderFollow

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


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
    last = deliveries.aggregate(sent=Max('sent_at'))['sent']
    return {'enabled': config.enabled, 'email': config.email, 'transport_ready': transport_ready(),
            'provider': settings.EMAIL_PROVIDER if settings.EMAIL_PROVIDER in ('smtp', 'resend') else 'unavailable',
            'pending': deliveries.filter(state='pending').count(),
            'failed': deliveries.filter(state='failed').count(),
            'last_sent_at': last.isoformat() if last else None}


@transaction.atomic
def save_settings(data):
    email, enabled = data.get('email', ''), data.get('enabled')
    if not isinstance(enabled, bool):
        raise ValidationError({'enabled': 'Izberite, ali želite e-poštna obvestila.'})
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
    changed = config.email != email or config.enabled != enabled
    if changed:
        # No old notifications are mailed after enabling or changing the recipient.
        config.enabled_since = timezone.now() if enabled else None
        NotificationEmail.objects.filter(owner_id=account_id(), state__in=['pending', 'failed']).update(state='cancelled')
    config.email, config.enabled = email, enabled
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
            f'Naslov ali pošiljanje uredite v Obvestila:\n{settings.PUBLIC_APP_URL}/#/obvestila\n')
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
            is_demo=False, active=True, type__in=['correction', 'deadline'],
            tender__data__source_type='real', created_at__gte=config.enabled_since,
            **follow_filter).exclude(pk__in=delivered).order_by('created_at', 'pk')[:max(0, limit - count)]
        for notification in notifications:
            subject, body = message(notification)
            _, created = NotificationEmail.objects.get_or_create(notification=notification, owner_id=config.owner_id,
                defaults={'recipient': config.email, 'sender': settings.DEFAULT_FROM_EMAIL, 'subject': subject, 'body': body})
            count += created
    return count


def send(delivery):
    host = urlsplit(settings.PUBLIC_APP_URL).hostname
    message_headers = {'Message-ID': f'<razpizi-notification-{delivery.notification_id}@{host}>'}
    if settings.EMAIL_PROVIDER == 'resend':
        response = requests.post('https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}',
                     'Idempotency-Key': f'notification/{delivery.delivery_key}/{delivery.pk}'},
            json={'from': delivery.sender, 'to': [delivery.recipient], 'subject': delivery.subject,
                  'text': delivery.body, 'headers': message_headers},
            timeout=settings.EMAIL_TIMEOUT, allow_redirects=False)
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise RuntimeError('Resend did not accept the message')
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not data['id'].strip():
            raise RuntimeError('Resend did not return a message identifier')
    else:
        sent = EmailMessage(delivery.subject, delivery.body, delivery.sender, [delivery.recipient],
                            headers=message_headers).send(fail_silently=False)
        if sent != 1:
            raise RuntimeError('SMTP did not accept the message')


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


def process(limit=20):
    enqueue()
    ids = list(NotificationEmail.objects.filter(state='pending', available_at__lte=timezone.now())
               .order_by('available_at', 'pk').values_list('pk', flat=True)[:limit])
    return sum(deliver(pk) for pk in ids)
