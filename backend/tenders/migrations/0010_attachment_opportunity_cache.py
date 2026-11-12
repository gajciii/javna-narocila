import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tenders', '0009_monthly_scan_item')]

    operations = [
        migrations.CreateModel(
            name='AttachmentOpportunityCache',
            fields=[
                ('tender', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                primary_key=True, serialize=False, to='tenders.tender')),
                ('fingerprint', models.CharField(max_length=64)),
                ('result', models.JSONField(default=dict)),
            ],
        ),
    ]
