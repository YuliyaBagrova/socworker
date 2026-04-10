# Generated manually for medical checkup dates

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_visit_task_reminder'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialworker',
            name='last_medical_checkup_date',
            field=models.DateField(
                blank=True,
                help_text='Для годовой проверки: осмотр считается актуальным 365 дней с этой даты.',
                null=True,
                verbose_name='Дата последнего медосмотра',
            ),
        ),
        migrations.AddField(
            model_name='socialworker',
            name='medical_checkup_planned_date',
            field=models.DateField(
                blank=True,
                help_text='Запланированная дата прохождения осмотра.',
                null=True,
                verbose_name='Медосмотр назначен на',
            ),
        ),
    ]
