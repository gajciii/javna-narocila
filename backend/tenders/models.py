from django.db import models


class CompanyProfile(models.Model):
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
    error = models.TextField(blank=True)


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
