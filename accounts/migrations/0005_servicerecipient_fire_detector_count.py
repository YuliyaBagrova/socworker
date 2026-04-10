from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_update_servicerecipient'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicerecipient',
            name='fire_detector_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Автономный пожарный извещатель — количество',
                verbose_name='АПИ количество',
            ),
        ),
    ]
