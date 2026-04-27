# Generated manually

from django.db import migrations, models


def register_existing_assigned(apps, schema_editor):
    ServiceRecipient = apps.get_model('accounts', 'ServiceRecipient')
    ServiceRecipient.objects.filter(social_worker_id__isnull=False).update(
        visit_planning_panel_registered=True,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_socialworker_medical_panel_registered'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerecipient',
            name='visit_planning_panel_registered',
            field=models.BooleanField(
                default=False,
                help_text='Подопечный отображается в таблице панели после добавления через «Запланировать визит».',
                verbose_name='Учитывается в панели планирования визитов',
            ),
        ),
        migrations.RunPython(register_existing_assigned, noop_reverse),
    ]
