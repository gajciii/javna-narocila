from django.db import models
from pgvector.django import HalfVectorField
from django.contrib.postgres.search import SearchVectorField
from django.conf import settings
from django.utils import timezone
import uuid


class WithoutVectorsManager(models.Manager):
    """Vectors are large and only used by explicit vector queries, so normal loads skip them."""
    def get_queryset(self):
        return super().get_queryset().defer('embedding')


class CompanyProfile(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=False)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class CompanyLookupCache(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    payload = models.JSONField(default=dict)
    fetched_at = models.DateTimeField()


class Tender(models.Model):
    id = models.SlugField(primary_key=True, max_length=100)
    data = models.JSONField(default=dict)
    following = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    embedding = HalfVectorField(dimensions=1024, null=True, blank=True)
    objects = WithoutVectorsManager()
    embedding_digest = models.CharField(max_length=32, blank=True)

    EMBEDDING_FIELDS = ('embedding', 'embedding_digest')

    def save(self, *args, **kwargs):
        # The worker writes vectors in the background; a full save of an older in-memory
        # copy must not overwrite them. Vectors are written only through queryset updates.
        if not self._state.adding and kwargs.get('update_fields') is None and not kwargs.get('force_insert'):
            kwargs['update_fields'] = [f.name for f in self._meta.concrete_fields
                                       if not f.primary_key and f.name not in self.EMBEDDING_FIELDS]
        super().save(*args, **kwargs)


class Document(models.Model):
    id = models.SlugField(primary_key=True, max_length=100)
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='document_records')
    title = models.CharField(max_length=300)
    path = models.TextField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, default='unprocessed')
    pages = models.JSONField(default=list)
    extraction = models.JSONField(default=dict)
    sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    indexed_content = models.ForeignKey('IndexedContent', null=True, blank=True, on_delete=models.SET_NULL)


class TenderQuestion(models.Model):
    """A question, answer or clarification published on the PJN dossier of a tender."""
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='questions')
    source_id = models.BigIntegerField()
    notice_id = models.CharField(max_length=20)
    kind = models.CharField(max_length=20)  # question, clarification
    question = models.TextField()
    answer = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tender', 'source_id'], name='unique_tender_question')]


class TenderConditions(models.Model):
    """All participation conditions of a tender, extracted from its current indexed documents."""
    tender = models.OneToOneField(Tender, on_delete=models.CASCADE, primary_key=True, related_name='condition_list')
    fingerprint = models.CharField(max_length=64)
    mode = models.CharField(max_length=12)  # live, empty, unavailable
    conditions = models.JSONField(default=list)
    message = models.TextField(blank=True)
    extracted_at = models.DateTimeField()


class IndexedContent(models.Model):
    """Profile-independent extraction shared by identical document bytes."""
    id = models.CharField(primary_key=True, max_length=64)
    sha256 = models.CharField(max_length=64, db_index=True)
    extractor_version = models.CharField(max_length=30)
    pages = models.JSONField(default=list)
    format = models.CharField(max_length=12)
    created_at = models.DateTimeField(auto_now_add=True)


class DocumentChunk(models.Model):
    content = models.ForeignKey(IndexedContent, on_delete=models.CASCADE, related_name='chunks')
    ordinal = models.PositiveIntegerField()
    page = models.PositiveIntegerField()
    locator = models.TextField()
    text = models.TextField()
    normalized_text = models.TextField()
    search_vector = SearchVectorField(null=True)
    embedding = HalfVectorField(dimensions=1024, null=True, blank=True)
    objects = WithoutVectorsManager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['content', 'ordinal'], name='unique_content_chunk')]


class PipelineJob(models.Model):
    """Durable PostgreSQL queue; leases recover work after a worker disconnect."""
    key = models.CharField(max_length=64, unique=True)
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=12)  # index or assess
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    state = models.CharField(max_length=12, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    available_at = models.DateTimeField()
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['state', 'available_at'], name='pipeline_pending_idx')]


class PipelineControl(models.Model):
    """Singleton row serializes collectors and controls the daily schedule."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    schedule_enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(default=timezone.now)


class PipelineRun(models.Model):
    source = models.CharField(max_length=12)  # manual, scheduled, cli, imported
    mode = models.CharField(max_length=12, default='monthly')
    period = models.CharField(max_length=7, blank=True)
    max_notices = models.PositiveIntegerField(null=True, blank=True)
    # Only notices whose submission deadline is still ahead are stored and indexed.
    open_only = models.BooleanField(default=False)
    skipped_count = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=12, default='queued')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    request_key = models.UUIDField(null=True, blank=True, unique=True)
    listed_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    error_log = models.JSONField(default=list)
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    # Set once, when collection has ended and none of the run's jobs is waiting or running.
    processed_at = models.DateTimeField(null=True)
    jobs = models.ManyToManyField(PipelineJob, through='PipelineRunItem', related_name='pipeline_runs')


class PipelineRunItem(models.Model):
    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE, related_name='items')
    job = models.ForeignKey(PipelineJob, on_delete=models.CASCADE)
    reused = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'job'], name='unique_pipeline_run_job')]


class PipelineAttempt(models.Model):
    job = models.ForeignKey(PipelineJob, on_delete=models.CASCADE, related_name='execution_history')
    lease = models.UUIDField(unique=True)
    number = models.PositiveIntegerField()
    worker = models.CharField(max_length=160, blank=True)
    state = models.CharField(max_length=12, default='running')
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True)
    error = models.TextField(blank=True)
    summary = models.JSONField(default=dict)


class PipelineAgent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    role = models.CharField(max_length=12)
    hostname = models.CharField(max_length=160)
    started_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    state = models.CharField(max_length=12, default='idle')
    job_id = models.BigIntegerField(null=True)
    run_id = models.BigIntegerField(null=True)


class TenderVersion(models.Model):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tender', 'version'], name='unique_tender_version')]


class Notification(models.Model):
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    event_key = models.CharField(max_length=180, unique=True)
    type = models.CharField(max_length=30)
    title = models.CharField(max_length=250)
    body = models.TextField()
    read = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=True)
    payload = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    company_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class SavedSearch(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)


class ImprovementPlan(models.Model):
    company_key = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=100)
    actions = models.JSONField(default=list)
    source_type = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Partner(models.Model):
    company_key = models.CharField(max_length=64, db_index=True)
    source_type = models.CharField(max_length=10)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DemoEvent(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SyncAttempt(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    source_id = models.CharField(max_length=100)
    success = models.BooleanField(default=False)
    raw = models.JSONField(default=dict)
    error = models.TextField(blank=True)


class SyncRun(models.Model):
    day = models.DateField()
    slot = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=20)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    result = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['day', 'slot'], name='unique_pjn_daily_slot')]


class EspdDraft(models.Model):
    company_key = models.CharField(max_length=64, db_index=True)
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='espd_drafts')
    answers = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company_key', 'tender'], name='unique_company_tender_espd')]


class PastAward(models.Model):
    """One awarded (or unawarded) lot from a published PJN award notice; public data, never demo."""
    id = models.CharField(primary_key=True, max_length=80)
    notice_id = models.CharField(max_length=30, db_index=True)
    dossier_id = models.CharField(max_length=30, blank=True, db_index=True)
    published_on = models.DateField(null=True)
    data = models.JSONField(default=dict)
    imported_at = models.DateTimeField(auto_now=True)
    embedding = HalfVectorField(dimensions=1024, null=True, blank=True)
    objects = WithoutVectorsManager()
    embedding_digest = models.CharField(max_length=32, blank=True)


class SimilarAwardsCache(models.Model):
    """AI-ranked similar awards per tender; reused while tender text and dataset stay the same."""
    tender = models.OneToOneField(Tender, on_delete=models.CASCADE, primary_key=True, related_name='similar_awards_cache')
    key = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now=True)


class RelevanceCache(models.Model):
    """The current company's Gemini content assessment for one tender and input fingerprint."""
    tender = models.OneToOneField(Tender, on_delete=models.CASCADE, primary_key=True, related_name='relevance_cache')
    key = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class AttachmentOpportunityCache(models.Model):
    tender = models.OneToOneField(Tender, on_delete=models.CASCADE, primary_key=True)
    fingerprint = models.CharField(max_length=64)
    result = models.JSONField(default=dict)


class MonthlyScanItem(models.Model):
    """Checkpoint and evidence for one published notice in a monthly archive scan."""
    period = models.CharField(max_length=7)
    notice_id = models.CharField(max_length=30)
    tender = models.ForeignKey(Tender, on_delete=models.SET_NULL, null=True, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=12, default='pending')
    result = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['period', 'notice_id'], name='unique_monthly_scan_notice')]


class EmailNotificationSettings(models.Model):
    """Email preferences for one account (null owner preserves legacy settings)."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    id = models.BigAutoField(primary_key=True)
    enabled = models.BooleanField(default=False)
    email = models.EmailField(blank=True)
    enabled_since = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationEmail(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='email_delivery')
    recipient = models.EmailField()
    sender = models.CharField(max_length=320, blank=True)
    delivery_key = models.UUIDField(default=uuid.uuid4, editable=False)
    subject = models.CharField(max_length=250)
    body = models.TextField()
    state = models.CharField(max_length=12, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['state', 'available_at'], name='notification_email_pending')]
        constraints = [models.UniqueConstraint(fields=['notification', 'owner'], name='unique_account_notification_email')]


class TenderFollow(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'tender'], name='unique_account_tender_follow')]


class NotificationRead(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'notification'], name='unique_account_notification_read')]
