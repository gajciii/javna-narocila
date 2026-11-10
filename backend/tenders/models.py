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
    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='notifications')
    event_key = models.CharField(max_length=180, unique=True)
    type = models.CharField(max_length=30)
    title = models.CharField(max_length=250)
    body = models.TextField()
    read = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class SavedSearch(models.Model):
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)


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
