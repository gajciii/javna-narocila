from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('tenders', '0007_past_awards')]

    operations = [
        migrations.CreateModel(
            name='RelevanceCache',
            fields=[
                ('tender', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                                                related_name='relevance_cache', serialize=False, to='tenders.tender')),
                ('key', models.CharField(max_length=64)),
                ('payload', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
