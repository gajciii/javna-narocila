from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import MagicMock, patch

import requests

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .email_notifications import deliver, enqueue, process, save_settings, status, transport_ready
from .models import EmailNotificationSettings, Notification, NotificationEmail, Tender


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
        self.assertIn('https://razpizi.example.com/#/obvestila', message.body)
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
