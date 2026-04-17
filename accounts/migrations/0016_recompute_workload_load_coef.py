# Generated manually — пересчёт коэффициента нагрузки по формуле «часы / 168».

from django.db import migrations


def forwards(apps, schema_editor):
    from accounts.models import WorkloadRecord
    for wr in WorkloadRecord.objects.iterator():
        wr.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_workload_norm_168_and_help'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
