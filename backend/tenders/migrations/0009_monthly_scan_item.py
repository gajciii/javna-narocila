from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('tenders', '0008_relevance_cache')]

    operations = [
        migrations.CreateModel(
            name='MonthlyScanItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period', models.CharField(max_length=7)),
                ('notice_id', models.CharField(max_length=30)),
                ('fingerprint', models.CharField(blank=True, max_length=64)),
                ('state', models.CharField(default='pending', max_length=12)),
                ('result', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tender', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='tenders.tender')),
            ],
        ),
        migrations.AddConstraint(
            model_name='monthlyscanitem',
            constraint=models.UniqueConstraint(fields=('period', 'notice_id'), name='unique_monthly_scan_notice'),
        ),
    ]
