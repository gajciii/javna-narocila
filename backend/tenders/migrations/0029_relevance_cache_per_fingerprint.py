from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Rebuild the relevance cache keyed by (tender, fingerprint).

    The old table held one row per tender for whichever company was scored last; its rows are
    only a cache and are recomputed on demand, so dropping them is safe.
    """

    dependencies = [('tenders', '0028_contracts')]

    operations = [
        migrations.DeleteModel(name='RelevanceCache'),
        migrations.CreateModel(
            name='RelevanceCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64)),
                ('payload', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='relevance_cache', to='tenders.tender')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('tender', 'key'), name='relevance_cache_tender_key')],
                'indexes': [models.Index(fields=['updated_at'], name='relevance_cache_updated')],
            },
        ),
    ]
