# Generated manually

from django.db import migrations, models


def set_all_registered(apps, schema_editor):
    SocialWorker = apps.get_model('accounts', 'SocialWorker')
    SocialWorker.objects.update(medical_panel_registered=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_socialworker_medical_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialworker',
            name='medical_panel_registered',
            field=models.BooleanField(
                default=False,
                help_text='Сотрудник появляется в таблице после «Назначить медосмотр».',
                verbose_name='Учёт в панели «Прохождение медосмотра»',
            ),
        ),
        migrations.RunPython(set_all_registered, noop_reverse),
    ]
