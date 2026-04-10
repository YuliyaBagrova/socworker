from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_safety_briefing_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='safetybriefingrecord',
            name='passed',
            field=models.BooleanField(
                default=True,
                help_text='Если снято — запись ожидает подтверждения прохождения.',
                verbose_name='Инструктаж пройден',
            ),
        ),
    ]
