from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_servicerecipient'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='socialworker',
            name='email',
        ),
        migrations.RemoveField(
            model_name='socialworker',
            name='position',
        ),
        migrations.AddField(
            model_name='socialworker',
            name='medical_checkup',
            field=models.CharField(
                choices=[('passed', 'Пройден'), ('not_passed', 'Не пройден'), ('expired', 'Просрочен')],
                default='not_passed',
                max_length=20,
                verbose_name='Медицинский осмотр',
            ),
        ),
    ]
