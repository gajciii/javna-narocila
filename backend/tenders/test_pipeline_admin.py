import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from .models import PipelineAgent, PipelineAttempt, PipelineControl, PipelineJob, PipelineRun, PipelineRunItem, Tender
from .pipeline_jobs import claim, enqueue_index, finish
from .pipeline_runs import create_run, claim_run, collect_run

BASE = '/api/admin/pipeline'
PASSWORD = 'test-only-administrator-password'


@override_settings(PIPELINE_REMOTE=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user('admin', password=PASSWORD, is_staff=True)
        cls.member = get_user_model().objects.create_user('member', password=PASSWORD)
        cls.tender = Tender.objects.create(pk='admin-test', data={'version': 1, 'title': 'Razpis za pregled'})

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.csrf = self.client.get(BASE + '/session').json()['csrf_token']

    def post(self, path, data=None, csrf=True):
        return self.client.post(BASE + path, data=data or {}, content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf if csrf else '', HTTP_ORIGIN='http://localhost:5174')

    def login(self, username='admin'):
        result = self.post('/login', {'username': username, 'password': PASSWORD})
        if result.status_code == 200:
            self.csrf = result.json()['csrf_token']
        return result

    def manual(self, **extra):
        return self.post('/runs', {'mode': 'existing', 'max_notices': 1,
            'request_key': str(uuid.uuid4()), **extra})

    def test_anonymous_and_nonstaff_cannot_read_or_start_pipeline(self):
        for path in ('/overview', '/runs', '/jobs'):
            self.assertEqual(self.client.get(BASE + path).status_code, 403)
        self.assertEqual(self.manual().status_code, 403)
        self.assertEqual(self.login('member').status_code, 403)
        self.assertFalse(PipelineRun.objects.filter(source='manual').exists())

    def test_login_and_mutations_require_csrf_and_logout_revokes_access(self):
        self.assertEqual(self.post('/login', {'username': 'admin', 'password': PASSWORD}, csrf=False).status_code, 403)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.post('/schedule', {'enabled': False}, csrf=False).status_code, 403)
        self.assertEqual(self.post('/schedule', {'enabled': False}).status_code, 200)
        self.assertFalse(PipelineControl.objects.get(pk=1).schedule_enabled)
        self.assertEqual(self.post('/logout').status_code, 200)
        self.assertEqual(self.client.get(BASE + '/overview').status_code, 403)

    @patch('tenders.pipeline_runs.collect_notice')
    def test_manual_request_is_async_and_idempotent(self, collect):
        self.login()
        key = str(uuid.uuid4())
        first, second = self.manual(request_key=key), self.manual(request_key=key)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(PipelineRun.objects.filter(source='manual').count(), 1)
        self.assertFalse(PipelineJob.objects.exists())
        collect.assert_not_called()
        self.assertEqual(self.manual(request_key=key, max_notices=2).status_code, 400)
        run = claim_run()
        self.assertEqual(run.requested_by, self.admin)
        collect_run(run)
        self.assertEqual(run.state, 'collected')
        self.assertEqual(run.jobs.count(), 1)
        result = self.client.get(BASE + f'/runs/{run.pk}').json()
        self.assertEqual(result['run']['jobs']['pending'], 1)

    def test_invalid_limits_and_future_period_are_rejected(self):
        self.login()
        for value in (0, -1, 5001, True, 1.2, '10'):
            with self.subTest(value=value):
                self.assertEqual(self.manual(max_notices=value).status_code, 400)
        self.assertEqual(self.manual(mode='monthly', period='2099-11').status_code, 400)
        self.assertEqual(self.manual(mode='unknown').status_code, 400)
        self.assertEqual(self.client.get(BASE + '/runs?page=0').status_code, 400)
        self.assertEqual(self.client.get(BASE + '/jobs?state=unknown').status_code, 400)
        self.assertFalse(PipelineRun.objects.filter(source='manual').exists())

    def test_staff_projection_omits_credentials_profile_payload_and_quotes(self):
        self.login()
        job = enqueue_index(self.tender)
        job.payload = {'profile': {'description': 'hidden-company-data'}, 'token': 'secret-value'}
        job.result = {'findings': [{'quote': 'hidden-evidence'}]}
        job.save()
        for url in ('/jobs', f'/jobs/{job.pk}', '/overview'):
            response = self.client.get(BASE + url)
            self.assertEqual(response.status_code, 200)
            for private in ('hidden-company-data', 'secret-value', 'hidden-evidence', PASSWORD):
                self.assertNotIn(private, response.content.decode())

    def test_retry_creates_audited_manual_run_and_preserves_attempts(self):
        self.login()
        job = enqueue_index(self.tender)
        active = claim(worker='test-worker')
        finish(active, {}, state='failed', error='Test failure')
        self.assertEqual(self.post(f'/jobs/{job.pk}').status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.execution_history.count(), 1)
        retry = PipelineRun.objects.get(source='manual', mode='retry')
        self.assertEqual(retry.requested_by, self.admin)
        self.assertEqual(retry.jobs.get(), job)
        self.assertEqual(self.post(f'/jobs/{job.pk}').status_code, 409)

    def test_agent_online_status_uses_recent_heartbeat(self):
        self.login()
        PipelineAgent.objects.create(role='worker', hostname='worker-live')
        PipelineAgent.objects.create(role='scheduler', hostname='scheduler-old', last_seen=timezone.now()-timedelta(minutes=5))
        result = self.client.get(BASE + '/overview').json()
        states = {agent['hostname']: agent['online'] for agent in result['agents']}
        self.assertTrue(states['worker-live'])
        self.assertFalse(states['scheduler-old'])


class CollectionTests(TestCase):
    def setUp(self):
        self.tender = Tender.objects.create(pk='collection-test', data={'version': 1,
            'source_metadata': {'notice_id': '1001'}})

    def test_paused_schedule_allows_manual_runs_and_collectors_do_not_overlap(self):
        PipelineControl.objects.filter(pk=1).update(schedule_enabled=False)
        self.assertIsNone(claim_run(schedule=True))
        manual = create_run(source='manual', mode='existing', max_notices=1)
        first = claim_run(schedule=True)
        self.assertEqual(first.pk, manual.pk)
        create_run(source='manual', mode='existing', max_notices=1)
        self.assertIsNone(claim_run(schedule=True))
        collect_run(first)
        self.assertIsNotNone(claim_run(schedule=True))

    def test_interrupted_collection_replays_without_duplicate_memberships(self):
        original = enqueue_index(self.tender)
        create_run(source='cli', mode='existing')
        first = claim_run()
        PipelineRunItem.objects.create(run=first, job=original, reused=True)
        PipelineRun.objects.filter(pk=first.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        replacement = claim_run()
        self.assertNotEqual(first.lease, replacement.lease)
        collect_run(replacement)
        self.assertEqual(replacement.jobs.count(), 1)
        self.assertEqual(replacement.items.get().reused, True)

    @patch('tenders.pipeline_runs.time.sleep')
    @patch('tenders.pipeline_runs.collect_notice', return_value={'mode': 'unavailable'})
    @patch('tenders.pipeline_runs.grid_rows', return_value=iter(['1001', '1002']))
    def test_collection_records_metadata_errors_and_continues(self, grid, collect, sleep):
        create_run(source='cli', period=timezone.localdate().strftime('%Y-%m'))
        run = claim_run()
        collect_run(run)
        self.assertEqual(run.state, 'partial')
        self.assertEqual(run.listed_count, 2)
        self.assertEqual(run.error_count, 1)
        self.assertEqual(run.error_log[0]['notice_id'], '1002')
        self.assertEqual(run.jobs.count(), 1)

    def test_job_attempt_history_is_fenced_by_lease(self):
        enqueue_index(self.tender)
        first = claim(worker='first-worker')
        PipelineJob.objects.filter(pk=first.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        replacement = claim(worker='second-worker')
        self.assertFalse(finish(first, {}, 'complete'))
        self.assertTrue(finish(replacement, {}, 'complete'))
        old = PipelineAttempt.objects.get(lease=first.lease)
        new = PipelineAttempt.objects.get(lease=replacement.lease)
        self.assertEqual(old.state, 'interrupted')
        self.assertEqual(new.state, 'complete')
        self.assertIsNotNone(old.finished_at)
