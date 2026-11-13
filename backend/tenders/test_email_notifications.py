from datetime import datetime, timedelta
from smtplib import SMTPException
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import requests

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .accounts import account_scope
from .email_notifications import (deliver, deliver_digest, enqueue, enqueue_digests, next_digest_at,
                                  process, save_settings, status, transport_ready)
from .models import (CompanyProfile, EmailNotificationSettings, Notification, NotificationEmail,
                     Tender, TenderDigestEmail, TenderFollow, TenderIgnore)


@override_settings(EMAIL_PROVIDER='smtp', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.com', DEFAULT_FROM_EMAIL='RazpIzi <notice@example.com>',
    PUBLIC_APP_URL='https://razpizi.example.com', EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
class EmailNotificationTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(id='email-test', following=True, data={
            'source_type': 'real', 'title': 'Razvoj platforme', 'buyer': 'Občina Primer'})
        self.counter = 0

    def enable(self, email='user@example.com'):
        return save_settings({'enabled': True, 'email': email})

    def notification(self, **changes):
        self.counter += 1
        values = {'tender': self.tender, 'event_key': f'email-test-{self.counter}',
                  'type': 'correction', 'is_demo': False, 'title': 'Sprememba spremljanega razpisa',
                  'body': 'Rok: 1. 12. → 3. 12. Preglejte popravek.'}
        values.update(changes)
        return Notification.objects.create(**values)

    def test_only_future_followed_real_changes_are_sent_once(self):
        self.notification()  # Must not send the history from before opt-in.
        self.enable()
        change = self.notification()
        deadline = self.notification(type='deadline')
        self.notification(type='new')
        self.notification(type='improvement')
        self.notification(is_demo=True)
        self.notification(active=False)
        self.notification(tender=None)
        other = Tender.objects.create(id='not-followed', data={'source_type': 'real'})
        self.notification(tender=other)
        demo = Tender.objects.create(id='demo', following=True, data={'source_type': 'demo'})
        self.notification(tender=demo)
        self.assertEqual(process(), 2)
        self.assertEqual(process(), 0)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(set(NotificationEmail.objects.values_list('notification_id', flat=True)), {change.pk, deadline.pk})
        message = mail.outbox[0]
        self.assertEqual(message.to, ['user@example.com'])
        self.assertIn('https://razpizi.example.com/#/razpisi/email-test?tab=changes', message.body)
        self.assertIn('https://razpizi.example.com/#/racun', message.body)
        self.assertIn('Občina Primer', message.body)
        self.assertIn('Sprememba roka', mail.outbox[1].subject)
        self.assertEqual(status()['pending'], 0)
        self.assertIsNotNone(status()['last_sent_at'])

    def test_read_state_does_not_change_email_delivery(self):
        self.enable()
        self.notification(read=True)
        self.assertEqual(process(), 1)

    def test_disabled_or_unconfigured_does_not_send_or_consume_notifications(self):
        self.notification()
        self.assertEqual(process(), 0)
        self.enable()
        self.notification()
        with override_settings(EMAIL_HOST=''):
            self.assertFalse(status()['transport_ready'])
            self.assertEqual(process(), 0)
        self.assertEqual(NotificationEmail.objects.count(), 0)
        self.assertEqual(process(), 1)

    def test_public_url_sender_and_tls_settings_are_required(self):
        for values in [{'PUBLIC_APP_URL': ''}, {'DEFAULT_FROM_EMAIL': ''},
                       {'DEFAULT_FROM_EMAIL': 'invalid'}, {'EMAIL_USE_SSL': True}]:
            with override_settings(**values):
                self.assertFalse(transport_ready())

    def test_settings_validate_email_and_boolean_and_expose_no_credentials(self):
        client = APIClient()
        url = '/api/notifications/email-settings'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['enabled'])
        for payload in [{'email': 'invalid', 'enabled': True}, {'email': [], 'enabled': True},
                        {'email': 'a@example.com', 'enabled': 'true'}, {'email': 'a@example.com\nBcc: b@example.com', 'enabled': True}]:
            self.assertEqual(client.put(url, payload, format='json').status_code, 400)
        with override_settings(EMAIL_HOST_PASSWORD='never-return-this'):
            response = client.put(url, {'email': ' user@example.com ', 'enabled': True}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['email'], 'user@example.com')
            self.assertNotIn('never-return-this', str(response.data))

    def test_disable_and_recipient_change_cancel_pending_and_do_not_backfill(self):
        self.enable()
        self.notification()
        enqueue()
        save_settings({'enabled': False, 'email': 'user@example.com'})
        self.assertEqual(NotificationEmail.objects.get().state, 'cancelled')
        self.assertEqual(process(), 0)
        self.notification()  # Occurred while disabled.
        self.enable('new@example.com')
        self.assertEqual(process(), 0)
        fresh = self.notification()
        self.assertEqual(enqueue(), 1)
        self.enable('third@example.com')
        self.assertEqual(process(), 0)
        self.assertEqual(NotificationEmail.objects.get(notification=fresh).state, 'cancelled')
        self.notification()
        self.assertEqual(process(), 1)
        self.assertEqual(mail.outbox[0].to, ['third@example.com'])

    def test_only_chosen_types_are_sent_and_deselected_pending_is_cancelled(self):
        self.assertEqual(status()['types'], ['correction', 'deadline'])
        self.enable()
        correction, deadline = self.notification(), self.notification(type='deadline')
        enqueue()
        save_settings({'enabled': True, 'email': 'user@example.com', 'types': ['deadline']})
        states = dict(NotificationEmail.objects.values_list('notification_id', 'state'))
        self.assertEqual(states, {correction.pk: 'cancelled', deadline.pk: 'pending'})
        self.notification()
        later = self.notification(type='deadline')
        self.assertEqual(process(), 2)
        self.assertEqual(set(NotificationEmail.objects.filter(state='sent').values_list('notification_id', flat=True)),
                         {deadline.pk, later.pk})
        self.assertEqual(status()['types'], ['deadline'])

    def test_types_are_validated(self):
        client, url = APIClient(), '/api/notifications/email-settings'
        for types in [['new'], 'deadline', [1], []]:
            response = client.put(url, {'email': 'a@example.com', 'enabled': True,
                                        'types': types, 'digest_enabled': False}, format='json')
            self.assertEqual(response.status_code, 400, types)
        response = client.put(url, {'email': 'a@example.com', 'enabled': True,
                                    'types': [], 'digest_enabled': True, 'digest_frequency': 'weekly'}, format='json')
        self.assertEqual((response.status_code, response.data['digest_frequency']), (200, 'weekly'))
        for frequency in ('hourly', None, []):
            self.assertEqual(client.put(url, {'email': 'a@example.com', 'enabled': True,
                'types': [], 'digest_frequency': frequency}, format='json').status_code, 400)
        response = client.put(url, {'email': 'a@example.com', 'enabled': False, 'types': []}, format='json')
        self.assertEqual((response.status_code, response.data['types']), (200, []))

    def test_saving_unchanged_settings_keeps_pending_and_original_cutoff(self):
        self.enable()
        self.notification()
        enqueue()
        before = EmailNotificationSettings.objects.get().enabled_since
        self.enable()
        self.assertEqual(EmailNotificationSettings.objects.get().enabled_since, before)
        self.assertEqual(process(), 1)

    def test_unfollow_or_inactive_event_cancels_pending(self):
        self.enable()
        n = self.notification()
        enqueue()
        self.tender.following = False
        self.tender.save()
        self.assertEqual(process(), 0)
        self.assertEqual(NotificationEmail.objects.get(notification=n).state, 'cancelled')

    def test_failures_retry_without_blocking_or_exposing_smtp_error(self):
        self.enable()
        self.notification()
        with patch('tenders.email_notifications.EmailMessage.send', side_effect=SMTPException('private credentials')):
            self.assertEqual(process(), 0)
        delivery = NotificationEmail.objects.get()
        self.assertEqual((delivery.state, delivery.attempts), ('pending', 1))
        self.assertNotIn('private credentials', delivery.error)
        self.assertGreater(delivery.available_at, timezone.now())
        self.assertEqual(process(), 0)  # Not due yet.
        delivery.available_at = timezone.now() - timedelta(seconds=1)
        delivery.save()
        self.assertEqual(process(), 1)
        delivery.refresh_from_db()
        self.assertEqual((delivery.state, delivery.attempts, delivery.error), ('sent', 2, ''))
        self.assertIn(str(delivery.notification_id), mail.outbox[0].extra_headers['Message-ID'])
        self.assertFalse(deliver(delivery.pk))

    def test_retry_limit_and_silent_zero_result(self):
        self.enable()
        self.notification()
        enqueue()
        delivery = NotificationEmail.objects.get()
        delivery.attempts = 4
        delivery.save()
        with patch('tenders.email_notifications.EmailMessage.send', return_value=0):
            self.assertEqual(process(), 0)
        delivery.refresh_from_db()
        self.assertEqual((delivery.state, delivery.attempts), ('failed', 5))
        self.assertEqual(status()['failed'], 1)
        with patch('tenders.email_notifications.EmailMessage.send') as send:
            self.assertEqual(process(), 0)
            send.assert_not_called()

    def test_enqueued_body_is_a_snapshot_and_subject_cannot_inject_headers(self):
        self.enable()
        self.tender.data['title'] = 'Razpis\r\nBcc: attacker@example.com'
        self.tender.save()
        n = self.notification()
        enqueue()
        n.body = 'Poznejše besedilo'
        n.save()
        self.assertEqual(process(), 1)
        self.assertNotIn('\n', mail.outbox[0].subject)
        self.assertNotIn('Poznejše besedilo', mail.outbox[0].body)
        self.assertIn('1. 12.', mail.outbox[0].body)

    def test_command_processes_outbox(self):
        from django.core.management import call_command
        self.enable()
        self.notification()
        call_command('send_notification_emails', verbosity=0)
        self.assertEqual(NotificationEmail.objects.get().state, 'sent')


@override_settings(EMAIL_PROVIDER='resend', RESEND_API_KEY='re_test_not_sent', EMAIL_HOST='',
    DEFAULT_FROM_EMAIL='RazpIzi <notice@example.com>', PUBLIC_APP_URL='https://razpizi.example.com',
    EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
class ResendNotificationTests(TestCase):
    setUp = EmailNotificationTests.setUp
    enable = EmailNotificationTests.enable
    notification = EmailNotificationTests.notification

    def response(self, status=200, data=None):
        response = MagicMock(status_code=status)
        response.json.return_value = {'id': 'resend-message-id'} if data is None else data
        return response

    @patch('tenders.email_notifications.requests.post')
    @patch('tenders.email_notifications.EmailMessage.send')
    def test_resend_sends_with_server_key_and_without_smtp(self, smtp, post):
        post.return_value = self.response()
        self.assertTrue(transport_ready())  # SMTP host/TLS settings are irrelevant to Resend.
        self.enable()
        n = self.notification()
        self.assertEqual(process(), 1)
        self.assertEqual(process(), 0)
        post.assert_called_once()
        smtp.assert_not_called()
        self.assertEqual(post.call_args.args[0], 'https://api.resend.com/emails')
        args = post.call_args.kwargs
        self.assertEqual(args['headers']['Authorization'], 'Bearer re_test_not_sent')
        self.assertTrue(args['headers']['Idempotency-Key'].startswith('notification/'))
        self.assertEqual(args['json']['from'], 'RazpIzi <notice@example.com>')
        self.assertEqual(args['json']['to'], ['user@example.com'])
        self.assertIn(n.body, args['json']['text'])
        self.assertEqual(args['timeout'], 10)
        self.assertFalse(args['allow_redirects'])

    @patch('tenders.email_notifications.requests.post')
    def test_missing_key_and_invalid_provider_do_not_send_or_fall_back(self, post):
        self.enable()
        self.notification()
        with override_settings(RESEND_API_KEY=''):
            self.assertFalse(transport_ready())
            self.assertEqual(process(), 0)
        with override_settings(EMAIL_PROVIDER='unknown', EMAIL_HOST='smtp.example.com'):
            self.assertFalse(transport_ready())
            self.assertEqual(process(), 0)
        post.assert_not_called()

    @patch('tenders.email_notifications.requests.post')
    def test_timeout_retry_reuses_key_and_payload_even_if_sender_changes(self, post):
        self.enable()
        self.notification()
        post.side_effect = [requests.Timeout('private details'), self.response()]
        self.assertEqual(process(), 0)
        first_args = post.call_args.kwargs
        delivery = NotificationEmail.objects.get()
        self.assertEqual(delivery.attempts, 1)
        delivery.available_at = timezone.now() - timedelta(seconds=1)
        delivery.save()
        with override_settings(DEFAULT_FROM_EMAIL='another@example.com'):
            self.assertEqual(process(), 1)
        self.assertEqual(first_args, post.call_args.kwargs)
        self.assertEqual(NotificationEmail.objects.get().state, 'sent')

    @patch('tenders.email_notifications.requests.post')
    @patch('tenders.email_notifications.EmailMessage.send')
    def test_error_redirect_or_invalid_success_is_not_recorded_as_sent(self, smtp, post):
        self.enable()
        http_error = self.response(status=500)
        http_error.raise_for_status.side_effect = requests.HTTPError('re_test_not_sent')
        invalid_json = self.response()
        invalid_json.json.side_effect = ValueError('bad JSON')
        for response in [http_error, self.response(status=302), self.response(data={}),
                         self.response(data={'id': None}), self.response(data=[]), invalid_json]:
            self.notification()
            enqueue()
            delivery = NotificationEmail.objects.latest('pk')
            post.return_value = response
            self.assertFalse(deliver(delivery.pk))
            delivery.refresh_from_db()
            self.assertEqual((delivery.state, delivery.attempts), ('pending', 1))
            self.assertNotIn('re_test_not_sent', delivery.error)
        smtp.assert_not_called()

    def test_settings_show_provider_but_never_api_key(self):
        response = APIClient().get('/api/notifications/email-settings')
        self.assertEqual(response.data['provider'], 'resend')
        self.assertTrue(response.data['transport_ready'])
        self.assertNotIn('re_test_not_sent', str(response.data))

    @override_settings(EMAIL_PROVIDER='smtp', EMAIL_HOST='smtp.example.com', EMAIL_USE_SSL=False,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('tenders.email_notifications.requests.post')
    def test_smtp_still_works_when_a_resend_key_is_present(self, post):
        self.enable()
        self.notification()
        self.assertEqual(process(), 1)
        post.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)


@override_settings(EMAIL_PROVIDER='smtp', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.com', DEFAULT_FROM_EMAIL='RazpIzi <notice@example.com>',
    PUBLIC_APP_URL='https://razpizi.example.com', EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
class TestEmailTests(TestCase):
    url = '/api/notifications/email-test'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_sends_to_saved_recipient_and_limits_rate(self):
        save_settings({'enabled': False, 'email': 'user@example.com'})
        client = APIClient()
        response = client.post(self.url)
        self.assertEqual((response.status_code, response.data['sent']), (200, True))
        self.assertEqual(mail.outbox[0].to, ['user@example.com'])
        self.assertIn('Testno', mail.outbox[0].subject)
        self.assertEqual(client.post(self.url).status_code, 429)
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(NotificationEmail.objects.exists())

    def test_reports_missing_settings_and_recipient(self):
        self.assertIn('naslov', APIClient().post(self.url).data['message'])
        save_settings({'enabled': False, 'email': 'user@example.com'})
        from django.core.cache import cache
        cache.clear()
        with override_settings(EMAIL_PROVIDER='resend', RESEND_API_KEY='', DEFAULT_FROM_EMAIL=''):
            data = APIClient().post(self.url).data
        self.assertFalse(data['sent'])
        self.assertIn('RESEND_API_KEY', data['message'])
        self.assertIn('DEFAULT_FROM_EMAIL', data['message'])
        self.assertEqual(len(mail.outbox), 0)

    @patch('tenders.email_notifications.requests.post')
    def test_resend_rejection_explains_why_without_the_key(self, post):
        save_settings({'enabled': False, 'email': 'user@example.com'})
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"message": "The example.com domain is not verified."}'
        post.return_value = response
        with override_settings(EMAIL_PROVIDER='resend', RESEND_API_KEY='re_secret'):
            data = APIClient().post(self.url).data
        self.assertFalse(data['sent'])
        self.assertIn('403', data['message'])
        self.assertIn('not verified', data['message'])
        self.assertNotIn('re_secret', str(data))


@override_settings(EMAIL_PROVIDER='smtp', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp.example.com', DEFAULT_FROM_EMAIL='RazpIzi <notice@example.com>',
    PUBLIC_APP_URL='https://razpizi.example.com', EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
class TenderDigestTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.ana = users.create_user('ana@example.com', email='ana@example.com')
        self.bor = users.create_user('bor@example.com', email='bor@example.com')
        CompanyProfile.objects.create(owner=self.ana, is_active=True,
                                      data={'name': 'Razvoj', 'activity': 'Razvoj spletnih platform'})
        CompanyProfile.objects.create(owner=self.bor, is_active=True,
                                      data={'name': 'Gradnja', 'activity': 'Gradnja in gradbena dela'})

    def enable(self, user, frequency='daily'):
        with account_scope(user.pk):
            return save_settings({'enabled': True, 'email': user.email, 'types': ['correction', 'deadline'],
                                  'digest_enabled': True, 'digest_frequency': frequency})

    def tender(self, pk, title, **changes):
        data = {'source_type': 'real', 'title': title, 'summary': title, 'buyer': 'Občina Primer',
                'kind': 'services', 'status': 'open', 'deadline': (timezone.now() + timedelta(days=30)).isoformat()}
        data.update(changes)
        return Tender.objects.create(pk=pk, data=data)

    def due(self, *users):
        EmailNotificationSettings.objects.filter(owner__in=users).update(digest_next_at=timezone.now() - timedelta(seconds=1))

    def test_daily_digest_selects_new_open_suitable_tenders_per_account(self):
        old = self.tender('old', 'Razvoj stare spletne platforme')
        self.enable(self.ana)
        self.enable(self.bor)
        fit = self.tender('web', 'Razvoj spletne platforme')
        build = self.tender('build', 'Gradnja mostu', kind='works')
        hidden = self.tender('hidden', 'Razvoj skrite spletne aplikacije')
        TenderIgnore.objects.create(owner=self.ana, tender=hidden)
        self.tender('closed', 'Razvoj zaključene spletne platforme', status='closed')
        self.tender('demo', 'Razvoj demo spletne platforme', source_type='demo')
        self.due(self.ana, self.bor)

        self.assertEqual(process(), 2)
        self.assertEqual(process(), 0)
        self.assertEqual(TenderDigestEmail.objects.count(), 2)
        for user, expected, excluded in ((self.ana, fit.pk, build.pk), (self.bor, build.pk, fit.pk)):
            digest = TenderDigestEmail.objects.get(owner=user)
            self.assertEqual(digest.state, 'sent')
            self.assertIn(expected, digest.tender_ids)
            self.assertNotIn(excluded, digest.tender_ids)
            self.assertNotIn(old.pk, digest.tender_ids)
            if user == self.ana:
                self.assertNotIn(hidden.pk, digest.tender_ids)
            message = next(message for message in mail.outbox if message.to == [user.email])
            self.assertIn(f'/#/razpisi/{expected}', message.body)
            self.assertNotIn('zaključene', message.body)
            self.assertNotIn('demo', message.body)

    def test_weekly_schedule_keeps_followed_changes_immediate(self):
        self.enable(self.ana, 'weekly')
        tender = self.tender('web', 'Razvoj spletne platforme')
        TenderFollow.objects.create(owner=self.ana, tender=tender)
        Notification.objects.create(tender=tender, event_key='changed-web', type='deadline',
                                    title='Rok', body='Rok je spremenjen.', is_demo=False)
        self.assertEqual(process(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(TenderDigestEmail.objects.exists())
        self.due(self.ana)
        self.assertEqual(process(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('tedenski pregled', mail.outbox[1].subject.lower())
        next_at = EmailNotificationSettings.objects.get(owner=self.ana).digest_next_at
        local_next = timezone.localtime(next_at)
        self.assertEqual((local_next.weekday(), local_next.hour), (0, 8))

    def test_empty_digest_advances_window_without_sending(self):
        self.enable(self.ana)
        self.tender('road', 'Gradnja ceste', kind='works')
        self.due(self.ana)
        self.assertEqual(process(), 0)
        self.assertFalse(TenderDigestEmail.objects.exists())
        self.assertGreater(EmailNotificationSettings.objects.get(owner=self.ana).digest_next_at, timezone.now())

    def test_frequency_change_cancels_pending_digest_and_preserves_window(self):
        self.enable(self.ana)
        tender = self.tender('web', 'Razvoj spletne platforme')
        self.due(self.ana)
        self.assertEqual(enqueue_digests(), 1)
        old = TenderDigestEmail.objects.get(owner=self.ana)
        self.enable(self.ana, 'weekly')
        old.refresh_from_db()
        self.assertEqual(old.state, 'cancelled')
        self.due(self.ana)
        self.assertEqual(process(), 1)
        self.assertEqual(TenderDigestEmail.objects.get(state='sent').tender_ids, [tender.pk])
        self.assertEqual(process(), 0)

    def test_digest_delivery_retries_and_can_be_disabled(self):
        self.enable(self.ana)
        self.tender('web', 'Razvoj spletne platforme')
        self.due(self.ana)
        enqueue_digests()
        digest = TenderDigestEmail.objects.get(owner=self.ana)
        with patch('tenders.email_notifications.EmailMessage.send', side_effect=SMTPException('private details')):
            self.assertFalse(deliver_digest(digest.pk))
        digest.refresh_from_db()
        self.assertEqual((digest.state, digest.attempts), ('pending', 1))
        self.assertNotIn('private details', digest.error)
        TenderDigestEmail.objects.filter(pk=digest.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(process(), 1)
        self.assertFalse(deliver_digest(digest.pk))
        with account_scope(self.ana.pk):
            save_settings({'enabled': False, 'email': self.ana.email})
            self.assertEqual(status()['pending'], 0)

    def test_disabling_digest_cancels_pending_and_reenable_does_not_backfill(self):
        self.enable(self.ana)
        self.tender('web', 'Razvoj spletne platforme')
        self.due(self.ana)
        self.assertEqual(enqueue_digests(), 1)
        with account_scope(self.ana.pk):
            save_settings({'enabled': True, 'email': self.ana.email, 'digest_enabled': False})
        self.assertEqual(TenderDigestEmail.objects.get().state, 'cancelled')
        self.enable(self.ana)
        self.due(self.ana)
        self.assertEqual(process(), 0)
        self.assertFalse(TenderDigestEmail.objects.filter(state='sent').exists())

    def test_schedule_uses_slovenian_time_across_dst(self):
        slovenia = ZoneInfo('Europe/Ljubljana')
        before = datetime(2026, 3, 28, 9, tzinfo=slovenia)
        self.assertEqual(next_digest_at(before, 'daily'), datetime(2026, 3, 29, 8, tzinfo=slovenia))
        self.assertEqual(next_digest_at(before, 'weekly'), datetime(2026, 3, 30, 8, tzinfo=slovenia))
