from django.db import migrations, models


def activate_existing(apps, schema_editor):
    apps.get_model('tenders', 'CompanyProfile').objects.filter(pk=1).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [('tenders', '0020_semantic_embeddings')]
    operations = [
        migrations.AddField(model_name='companyprofile', name='is_active', field=models.BooleanField(default=False)),
        migrations.RunPython(activate_existing, migrations.RunPython.noop),
    ]
